"""Rebind persistent MCP handlers to a fresh trusted context for every Run."""

import asyncio
import os

from .catalog import Catalog, PROJECT_ROOT
from .access import resolve_data_access
from .connections import load_config, resolve_connection
from .context import DataContext, DataError
from .executor import Executor


def worker_secret_environment(payload, source_keys, env, *, catalog=None):
    """Select only registered, authorized connection secrets for this Worker."""
    if not source_keys or not env.get("CCSDK_DATA_CONFIG"):
        return {}
    context = DataContext.from_payload(payload)
    config, _ = load_config(env["CCSDK_DATA_CONFIG"], PROJECT_ROOT)
    catalog = catalog or Catalog()
    selected = {}
    for source_key in source_keys:
        try:
            source = catalog.source(source_key)
            resolve_data_access(context, source, config)
            connection = resolve_connection(context, source, config)
        except DataError:
            continue
        for field in ("username_ref", "password_ref"):
            ref = connection.get(field)
            if isinstance(ref, str) and ref.startswith("env:") and ref[4:] in env:
                selected[ref[4:]] = env[ref[4:]]
    return selected


class RunServices:
    def __init__(self, source_keys, *, config_path=None, env=None, catalog=None):
        self.env = dict(os.environ if env is None else env)
        self.config_path = config_path or self.env.get("CCSDK_DATA_CONFIG")
        self.catalog = catalog or Catalog()
        self.source_keys = tuple(source_keys)
        self.executor = None
        self.report = None
        self.tasks = set()
        self.lock = asyncio.Lock()

    async def bind(self, payload):
        await self.close()
        context = DataContext.from_payload(payload)
        config, base = load_config(self.config_path, PROJECT_ROOT)
        executor = Executor(context, config, self.env, base, self.catalog, self.source_keys)
        from reporting.bindings import load_template
        from reporting.planner import Planner
        template = load_template(context.template_key, context.capability_ref) if context.template_key else None
        if template:
            for source in template["source_roles"].values():
                executor.access(source)
        self.executor = executor
        self.artifact_directories = {k: payload.get(k) for k in
                                    ("session_directory", "deliverables_directory")}
        self.report = Planner(self, template) if template else None

    def current(self):
        if self.executor is None:
            raise DataError("RUN_NOT_ACTIVE")
        return self.executor

    async def call(self, function, *args, **kwargs):
        executor = self.current()
        async with self.lock:
            executor.connections.check()
            task = asyncio.create_task(asyncio.to_thread(function, *args, **kwargs))
            self.tasks.add(task)
            try:
                return await asyncio.shield(task)
            except asyncio.CancelledError:
                executor.connections.cancel()
                await asyncio.gather(task, return_exceptions=True)
                raise
            finally:
                self.tasks.discard(task)

    async def close(self):
        if self.executor:
            self.executor.connections.cancel()
        if self.report:
            await self.report.close()
        if self.tasks:
            await asyncio.gather(*self.tasks, return_exceptions=True)
        self.executor = None
        self.report = None
