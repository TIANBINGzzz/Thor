"""Protected deployment configuration; engines live only for a Run snapshot."""

from contextlib import contextmanager
from pathlib import Path
from threading import Event, Lock
import time

from sqlalchemy import URL, create_engine
from sqlalchemy.pool import NullPool

from .catalog import PROJECT_ROOT, key, read_json
from .context import DataError


def config_path(env):
    """按调用方环境解析部署配置路径，相对路径以仓库根目录为基准。"""
    location = Path(env.get('CCSDK_DATABASES_FILE') or 'config/databases.json')
    return (location if location.is_absolute() else PROJECT_ROOT / location).resolve()


def load_config(env, *, optional=False):
    """校验部署连接配置，补入来源标识和相对路径基准。"""
    location = config_path(env)
    if optional and not location.exists():
        return {}
    config = read_json(location)
    if not isinstance(config, dict) or config.get('version') != 1 or not isinstance(config.get('sources'), dict):
        raise DataError("CONFIG_INVALID")
    for source_key, entry in config['sources'].items():
        key(source_key)
        if not isinstance(entry, dict):
            raise DataError('CONFIG_INVALID')
        for field in ('connection', 'policy'):
            value = entry.get(field)
            if not isinstance(value, dict) or not value or 'source_key' in value:
                raise DataError('CONFIG_INVALID')
            value['source_key'] = source_key
        entry['connection']['_base_directory'] = location.parent
    return config['sources']


def resolve_connection(context, source, config):
    """独立校验来源与租户连接权限，返回本次连接配置副本。"""
    connection = dict(config['connection'])
    # 连接必须单独显式允许所有租户，不能仅凭来源策略放开其他连接。
    if (not connection.get("revision") or connection.get("source_key") != source["source_key"]
            or connection.get("tenant_id") not in ("*", context.tenant_id)):
        raise DataError("CONNECTION_FORBIDDEN")
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
