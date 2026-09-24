"""Rebind persistent MCP handlers to a fresh trusted context for every Run."""

import asyncio
import json
import os

from data_access.catalog import Catalog
from data_access.context import DataContext, DataError
from data_access.executor import Executor


class RunServices:
    def __init__(self, source_keys, *, env=None, catalog=None, context_topics=None):
        """保存本轮可用来源与私有环境副本，初始化串行调用和上下文状态。"""
        self.env = dict(os.environ if env is None else env)
        self.catalog = catalog or Catalog()
        self.source_keys = tuple(source_keys)
        if context_topics is not None and (not isinstance(context_topics, list)
                or any(not isinstance(topic, str) or not topic for topic in context_topics)):
            raise DataError('CONFIG_INVALID')
        self.context_topics = context_topics
        self._context_text = None
        self.executor = None
        self.tasks = set()
        self.lock = asyncio.Lock()

    async def bind(self, payload):
        """释放旧上下文后绑定可信 Run，核对模板版本与来源并准备所需数据。"""
        await self.close()
        context = DataContext.from_payload(payload)
        from workflows.writing_docx.template_assets import load_template
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
        if self.context_topics is not None:
            try:
                context = await self.call(executor.prepare_context, self.context_topics)
                self._context_text = json.dumps(context, ensure_ascii=False, separators=(',', ':'))
            except BaseException:
                await self.close()
                raise

    def prepare_prompt(self, prompt):
        """每轮查询携带新准备的上下文，持久 Client 不复用上一轮范围引用。"""
        if self.context_topics is None:
            return prompt
        self.current()
        if self._context_text is None:
            raise DataError('RUN_NOT_ACTIVE')
        return ('本轮数据库上下文（程序已准备，引用仅本轮有效）：\n<database_context>\n'
                + self._context_text + '\n</database_context>\n\n用户问题：\n' + prompt)

    def current(self):
        """返回当前 Run 的执行器，尚未绑定或已关闭时拒绝访问。"""
        if self.executor is None:
            raise DataError("RUN_NOT_ACTIVE")
        return self.executor

    async def call(self, function, *args, **kwargs):
        """在线程中串行执行数据库操作，取消时中断连接并等待操作收尾。"""
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
        """取消本轮数据库连接并等待在途调用结束，清空执行器与上下文。"""
        self._context_text = None
        if self.executor:
            self.executor.connections.cancel()
        if self.tasks:
            await asyncio.gather(*self.tasks, return_exceptions=True)
        self.executor = None
