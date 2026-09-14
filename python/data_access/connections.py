"""Protected deployment configuration; engines live only for a Run snapshot."""

from contextlib import contextmanager
from pathlib import Path
from threading import Event, Lock
import time

from sqlalchemy import URL, create_engine, text
from sqlalchemy.pool import NullPool

from .catalog import read_json
from .context import DataError


def load_config(path, base):
    if not path:
        raise DataError("DATA_CONFIG_REQUIRED")
    location = Path(path)
    if not location.is_absolute():
        location = Path(base) / location
    config = read_json(location)
    if config.get("version") != 1:
        raise DataError("CONFIG_INVALID")
    return config, location.resolve().parent


def secret(ref, env, base):
    if not isinstance(ref, str):
        raise DataError("SECRET_REQUIRED")
    if ref.startswith("env:"):
        value = env.get(ref[4:])
    elif ref.startswith("file:"):
        path = Path(ref[5:])
        value = (path if path.is_absolute() else base / path).read_text(encoding="utf-8").rstrip("\r\n")
    else:
        raise DataError("SECRET_REQUIRED")
    if not value:
        raise DataError("SECRET_REQUIRED")
    return value


def resolve_connection(context, source, config):
    connection = dict(config.get("connections", {}).get(source["connection_ref"], {}))
    if (not connection.get("revision") or connection.get("source_key") != source["source_key"]
            or connection.get("tenant_id") != context.tenant_id):
        raise DataError("CONNECTION_FORBIDDEN")
    return connection


class Connections:
    def __init__(self, env, base):
        self.env, self.base = env, base
        self.cancelled = Event()
        self._lock = Lock()
        self._active = set()

    def cancel(self):
        self.cancelled.set()
        # Interrupt local test databases and shut down a MySQL socket without
        # issuing another SQL statement on the connection being cancelled.
        with self._lock:
            for raw in self._active:
                if hasattr(raw, "interrupt"):
                    raw.interrupt()
                elif getattr(raw, "_sock", None):
                    try:
                        raw._sock.shutdown(2)
                    except OSError:
                        pass

    def check(self):
        if self.cancelled.is_set():
            raise DataError("CANCELLED")

    @contextmanager
    def snapshot(self, config):
        self.check()
        timeout = max(1, min(int(config.get("timeout_seconds", 30)), 120))
        driver = config.get("driver")
        args = {}
        if driver == "mysql+pymysql":
            tls = config.get("tls", {})
            mode = tls.get("mode", "verify_identity")
            if mode not in {"verify_identity", "disabled"}:
                raise DataError("TLS_CONFIG_INVALID")
            if mode == "verify_identity" and (not tls.get("ca_file") or tls.get("verify_identity") is not True):
                raise DataError("TLS_REQUIRED")
            url = URL.create(driver, username=secret(config.get("username_ref"), self.env, self.base),
                             password=secret(config.get("password_ref"), self.env, self.base),
                             host=config["host"], port=int(config.get("port", 3306)), database=config["database"])
            args = {"connect_timeout": timeout, "read_timeout": timeout, "write_timeout": timeout,
                    "local_infile": False, "charset": "utf8mb4"}
            if mode == "verify_identity":
                ca = Path(tls["ca_file"])
                args.update(ssl_ca=str(ca if ca.is_absolute() else self.base / ca),
                            ssl_verify_cert=True, ssl_verify_identity=True)
            else:
                args["ssl_disabled"] = True
        elif driver == "sqlite":
            path = Path(config["database"])
            path = (path if path.is_absolute() else self.base / path).resolve()
            if not path.is_file():
                raise DataError("CONNECTION_UNAVAILABLE")
            url = URL.create("sqlite", database=str(path))
        else:
            raise DataError("DRIVER_UNSUPPORTED")
        engine = create_engine(url, connect_args=args, poolclass=NullPool, hide_parameters=True)
        try:
            with engine.connect() as connection:
                raw = connection.connection.driver_connection
                with self._lock:
                    self._active.add(raw)
                try:
                    self.check()
                    if driver == "sqlite":
                        connection.exec_driver_sql("PRAGMA query_only = ON")
                        deadline = time.monotonic() + timeout
                        raw.set_progress_handler(lambda: int(self.cancelled.is_set() or time.monotonic() > deadline), 1000)
                        connection.exec_driver_sql("BEGIN")
                    else:
                        connection.exec_driver_sql(f"SET SESSION MAX_EXECUTION_TIME={timeout * 1000}")
                        connection.exec_driver_sql("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
                        connection.exec_driver_sql("START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY")
                    yield connection
                finally:
                    with self._lock:
                        self._active.discard(raw)
                    connection.rollback()
        finally:
            engine.dispose()
