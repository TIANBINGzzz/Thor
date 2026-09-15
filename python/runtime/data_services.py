"""Rebind persistent MCP handlers to a fresh trusted context for every Run."""

import asyncio
import os

from data_access.catalog import Catalog
from data_access.context import DataContext, DataError
from data_access.executor import Executor


class RunServices:
    def __init__(self, source_keys, *, env=None, catalog=None):
        self.env = dict(os.environ if env is None else env)
        self.catalog = catalog or Catalog()
        self.source_keys = tuple(source_keys)
        self.executor = None
        self.report = None
        self.tasks = set()
        self.lock = asyncio.Lock()

    async def bind(self, payload):
        await self.close()
        context = DataContext.from_payload(payload)
        executor = Executor(context, self.env, self.catalog, self.source_keys)
        from workflows.writing_docx.bindings import load_template
        from workflows.writing_docx.planner import Planner
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
