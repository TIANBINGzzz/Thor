"""Protected deployment configuration; engines live only for a Run snapshot."""

from contextlib import contextmanager
from pathlib import Path
from threading import Event, Lock
import time

from sqlalchemy import URL, create_engine
from sqlalchemy.pool import NullPool

from .catalog import PROJECT_ROOT, key
from runtime.deployment_config import deployment_section, validate_database_access
from .context import DataError


def load_config(env=None, *, optional=False):
    """读取启动时冻结的客户连接；表和指标边界只来自登记资产。"""
    config = deployment_section('databases', {})
    if not isinstance(config, dict):
        raise DataError('CONFIG_INVALID')
    for source_key, entry in config.items():
        key(source_key)
        if not isinstance(entry, dict) or set(entry) - {'connection', 'access', 'query'}:
            raise DataError('CONFIG_INVALID')
        connection, query = entry.get('connection'), entry.get('query', {})
        if (not isinstance(connection, dict) or not connection or 'source_key' in connection
                or not isinstance(query, dict)):
            raise DataError('CONFIG_INVALID')
        try:
            validate_database_access(entry.get('access'))
        except ValueError:
            raise DataError('CONFIG_INVALID') from None
        entry['connection'] = {**connection, 'source_key': source_key,
            '_base_directory': PROJECT_ROOT / 'config',
            **{k: query[k] for k in ('timeout_seconds', 'max_rows') if k in query}}
    return config


def resolve_connection(context, source, config):
    """连接来自可信来源配置，调用者不能用 Run 身份切换连接。"""
    connection = dict(config['connection'])
    if connection.get('source_key') != source['source_key']:
        raise DataError('CONNECTION_FORBIDDEN')
    return connection


class Connections:
    def __init__(self):
        """初始化本轮取消信号与受锁保护的活动连接集合。"""
        self.cancelled = Event()
        self._lock = Lock()
        self._active = set()

    def cancel(self):
        """标记本轮取消并中断活动连接，不额外执行 SQL。"""
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
        """取消后阻止继续建立连接或读取结果。"""
        if self.cancelled.is_set():
            raise DataError("CANCELLED")

    @contextmanager
    def snapshot(self, config):
        """建立有时限的只读事务快照，退出时回滚并释放连接。"""
        self.check()
        base = Path(config['_base_directory'])
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
            if any(not isinstance(config.get(key), str) or not config[key]
                   for key in ("username", "password")):
                raise DataError("SECRET_REQUIRED")
            url = URL.create(driver, username=config["username"],
                             password=config["password"],
                             host=config["host"], port=int(config.get("port", 3306)), database=config["database"])
            args = {"connect_timeout": timeout, "read_timeout": timeout, "write_timeout": timeout,
                    "local_infile": False, "charset": "utf8mb4"}
            if mode == "verify_identity":
                ca = Path(tls["ca_file"])
                args.update(ssl_ca=str(ca if ca.is_absolute() else base / ca),
                            ssl_verify_cert=True, ssl_verify_identity=True)
            else:
                args["ssl_disabled"] = True
        elif driver == "sqlite":
            path = Path(config["database"])
            path = (path if path.is_absolute() else base / path).resolve()
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
                        def should_interrupt():
                            """供 SQLite 进度回调在取消或超时时中断查询。"""
                            return int(self.cancelled.is_set() or time.monotonic() > deadline)

                        raw.set_progress_handler(should_interrupt, 1000)
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
