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
        self.workflow_revision = None
        self.tasks = set()
        self.lock = asyncio.Lock()

    async def bind(self, payload):
        await self.close()
        context = DataContext.from_payload(payload)
        from workflows.writing_docx.template_assets import load_template
        from workflows.writing_docx.report_planner import ReportPlanner
        template = load_template(context.template_key, context.capability_ref) if context.template_key else None
        selected = self.source_keys
        if template:
            expected = (payload.get('_workflow_assets') or {}).get('template_revision')
            if expected is not None and expected != template['_revision']:
                raise DataError('TEMPLATE_MISMATCH')
            selected = tuple(sorted(set(template['source_roles'].values())))
            if not set(selected) <= set(self.source_keys):
                raise DataError('SOURCE_FORBIDDEN')
        executor = Executor(context, self.env, self.catalog, selected)
        if template:
            for source in template["source_roles"].values():
                executor.access(source)
        self.executor = executor
        self.workflow_revision = (payload.get('_workflow_assets') or {}).get('revision')
        self.artifact_directories = {k: payload.get(k) for k in
                                    ("session_directory", "deliverables_directory")}
        self.report = ReportPlanner(self, template) if template else None

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
        self.workflow_revision = None
