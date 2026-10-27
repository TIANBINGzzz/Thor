import asyncio
import json
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest.mock import patch


def create_pack(root: Path, operations, code, *, ref='demo-capability'):
    pack = root / ref
    pack.mkdir(parents=True)
    (pack / '__init__.py').write_text('', encoding='utf-8')
    (pack / 'operations.py').write_text(textwrap.dedent(code), encoding='utf-8')
    (pack / 'pack.json').write_text(json.dumps({'ref': ref, 'operations': operations}), encoding='utf-8')
    return pack


def operation(ref='calculate', handler='calculate'):
    return {
        'ref': ref,
        'description': '执行测试操作',
        'inputSchema': {
            'type': 'object',
            'properties': {
                'value': {'type': 'string'},
                'fail': {'type': 'boolean'},
                'bad_output': {'type': 'boolean'},
            },
            'required': ['value'],
            'additionalProperties': False,
        },
        'outputSchema': {
            'type': 'object',
            'properties': {'answer': {'type': 'string'}},
            'required': ['answer'],
            'additionalProperties': False,
        },
        'handler': handler,
    }


class CapabilityOperationTests(unittest.IsolatedAsyncioTestCase):
    def _capability(self, directory: Path, *, operations=None):
        root = directory / 'demo-capability'
        root.mkdir(parents=True)
        manifest = {
            'ref': 'demo-capability',
            'title': '测试能力',
            'description': '测试能力',
            'supportsAttachments': False,
            'skillRefs': [],
            'toolRefs': [],
            'execution': {'mode': 'agent'},
        }
        if operations is not None:
            manifest['operationRefs'] = operations
        (root / 'capability.json').write_text(json.dumps(manifest), encoding='utf-8')
        (root / 'CAPABILITY.md').write_text('测试能力规则', encoding='utf-8')
        return root

    async def test_operation_server_validates_input_output_and_hides_failures(self):
        from runtime.capability_operations import build_operation_server

        with tempfile.TemporaryDirectory() as temp:
            temp = Path(temp)
            packs = temp / 'packs'
            create_pack(packs, [operation()], '''
                async def calculate(context, args):
                    if args.get('fail'):
                        raise RuntimeError('private detail')
                    if args.get('bad_output'):
                        return {'private': 'invalid'}
                    return {'answer': args['value']}
            ''')
            entry_dir = self._capability(temp / 'capabilities', operations=['calculate'])
            with patch('capability_packs.registry.PACK_ROOT', packs), \
                 patch('runtime.capability_operations.create_sdk_mcp_server', side_effect=lambda name, **kwargs: kwargs):
                entry = {'ref': 'demo-capability', 'operation_refs': ['calculate'],
                         '_directory': str(entry_dir)}
                server_name, server, names = build_operation_server(entry, {'run_id': 'run-1'})
                self.assertEqual(server_name, 'capability_ops')
                self.assertEqual(names, ['calculate'])
                tool = server['tools'][0]
                good = await tool.handler({'value': 'ok'})
                self.assertEqual(json.loads(good['content'][0]['text']), {'answer': 'ok'})
                invalid = await tool.handler({})
                self.assertTrue(invalid['isError'])
                self.assertEqual(json.loads(invalid['content'][0]['text'])['error']['code'], 'PARAMETERS_INVALID')
                bad_output = await tool.handler({'value': 'ok', 'bad_output': True})
                self.assertTrue(bad_output['isError'])
                self.assertEqual(json.loads(bad_output['content'][0]['text'])['error']['code'], 'RESULT_INVALID')
                failed = await tool.handler({'value': 'ok', 'fail': True})
                self.assertTrue(failed['isError'])
                text = failed['content'][0]['text']
                self.assertNotIn('private detail', text)
                self.assertEqual(json.loads(text)['error']['code'], 'OPERATION_FAILED')

    def test_capability_entry_requires_existing_declared_pack_operations(self):
        from runtime.capabilities import capability_entry

        with tempfile.TemporaryDirectory() as temp:
            temp = Path(temp)
            capabilities = temp / 'capabilities'
            entry_dir = self._capability(capabilities, operations=['missing'])
            packs = temp / 'packs'
            create_pack(packs, [operation()], 'async def calculate(context, args): return {}')
            with patch('runtime.capabilities.CAPABILITIES_ROOT', capabilities), \
                 patch('capability_packs.registry.PACK_ROOT', packs):
                with self.assertRaises(RuntimeError):
                    capability_entry(entry_dir, skills_root=temp / 'skills')

    def test_capability_discovery_reads_schema_without_executing_pack_code(self):
        from runtime.capabilities import capability_entry

        with tempfile.TemporaryDirectory() as temp:
            temp = Path(temp)
            capabilities = temp / 'capabilities'
            entry_dir = self._capability(capabilities, operations=['calculate'])
            packs = temp / 'packs'
            create_pack(packs, [operation()], "raise RuntimeError('code must not execute during discovery')")
            with patch('runtime.capabilities.CAPABILITIES_ROOT', capabilities), \
                 patch('capability_packs.registry.PACK_ROOT', packs):
                entry = capability_entry(entry_dir, skills_root=temp / 'skills')
            self.assertEqual(entry['operation_refs'], ['calculate'])

    def test_operation_manifest_is_parsed_once_per_worker(self):
        from capability_packs.registry import read_pack_manifest
        from runtime.asset_registry import read_manifest as parse_manifest

        with tempfile.TemporaryDirectory() as temp:
            packs = Path(temp)
            create_pack(packs, [operation()], "raise RuntimeError('manifest read must not execute code')")
            with patch('capability_packs.registry.PACK_ROOT', packs), \
                 patch('capability_packs.registry.read_manifest', wraps=parse_manifest) as read_manifest:
                first = read_pack_manifest('demo-capability')
                second = read_pack_manifest('demo-capability')
            self.assertIs(first, second)
            self.assertEqual(read_manifest.call_count, 1)

    def test_managed_capability_cannot_reference_code_pack(self):
        from runtime.capabilities import capability_entry

        with tempfile.TemporaryDirectory() as temp:
            temp = Path(temp)
            managed = temp / 'managed'
            entry_dir = self._capability(managed, operations=['calculate'])
            with patch('runtime.capabilities.MANAGED_CAPABILITIES_ROOT', managed):
                with self.assertRaises(RuntimeError):
                    capability_entry(entry_dir, skills_root=temp / 'skills')

    async def test_capability_context_reuses_document_and_artifact_services(self):
        from runtime.capability_operations import CapabilityContext

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for name in ('session', 'input', 'work', 'deliverables', 'extra'):
                (root / name).mkdir()
            events = []
            context = CapabilityContext.from_runtime({'ref': 'demo-capability'}, {
                'run_id': 'run-1', 'session_directory': root / 'session',
                'input_directory': root / 'input', 'work_directory': root / 'work',
                'deliverables_directory': root / 'deliverables',
                'additional_directories': [str(root / 'extra')],
                'artifact_sink': events.append,
            })
            with patch('tools.document_conversion.render_document', return_value={'pdfPath': 'x.pdf'}) as render:
                rendered = await context.documents.render('draft.docx', 'preview')
            self.assertEqual(rendered, {'pdfPath': 'x.pdf'})
            self.assertEqual(render.call_args.args[2], root / 'work')
            self.assertEqual(set(render.call_args.args[3]), {
                str(root / 'deliverables'), str(root / 'input'), str(root / 'extra')})
            self.assertNotIn(root / 'session', context.documents.roots)

            with patch('tools.artifacts.publish_artifact', return_value={
                    'artifactId': 'artifact-test', 'name': 'report.docx', 'size': 10, 'status': 'pending'}):
                receipt = await context.artifacts.publish('draft.docx', 'report.docx')
            self.assertEqual(receipt, {'artifactId': 'artifact-test', 'name': 'report.docx', 'size': 10})
            self.assertEqual(events, [{'type': 'artifact.published', 'artifactId': 'artifact-test'}])

    def test_capability_context_does_not_create_artifact_service_without_run_workspace(self):
        from runtime.capability_operations import CapabilityContext

        context = CapabilityContext.from_runtime({'ref': 'demo-capability'}, {
            'run_id': 'run-1', 'input_directory': '/tmp/input'})
        self.assertIsNone(context.artifacts)
        self.assertIsNotNone(context.documents)

    async def test_registered_tools_reject_missing_and_undeclared_operations(self):
        from runtime.tool_registry import build_registered_tools

        with tempfile.TemporaryDirectory() as temp:
            temp = Path(temp)
            with patch('capability_packs.registry.PACK_ROOT', temp / 'missing'):
                with self.assertRaises(RuntimeError):
                    build_registered_tools({'ref': 'demo-capability', 'tools': [], 'required_tools': [], 'operation_refs': ['calculate']}, {'run_id': 'run-1'})

            packs = temp / 'packs'
            create_pack(packs, [operation(ref='hidden', handler='execute')], '''
                async def execute(context, args): return {'answer': 'ok'}
            ''')
            with patch('capability_packs.registry.PACK_ROOT', packs):
                with self.assertRaises(RuntimeError):
                    build_registered_tools({'ref': 'demo-capability', 'tools': [], 'required_tools': [],
                        'operation_refs': ['calculate']},
                        {'run_id': 'run-1'})

    async def test_registered_tools_expose_only_declared_operation_names(self):
        from runtime.tool_registry import build_registered_tools

        with tempfile.TemporaryDirectory() as temp:
            packs = Path(temp) / 'packs'
            create_pack(packs, [operation(), operation(ref='hidden', handler='hidden')], '''
                async def calculate(context, args): return {'answer': 'ok'}
                async def hidden(context, args): return {'answer': 'private'}
            ''')
            with patch('capability_packs.registry.PACK_ROOT', packs), \
                 patch('runtime.capability_operations.create_sdk_mcp_server', side_effect=lambda name, **kwargs: kwargs):
                result = build_registered_tools({'ref': 'demo-capability', 'tools': [],
                    'required_tools': [], 'operation_refs': ['calculate']}, {'run_id': 'run-1'})
            self.assertEqual(result.exact_tools['capability_ops'], ['calculate'])
            self.assertNotIn('hidden', result.exact_tools['capability_ops'])
            self.assertNotIn('capability_ops', result.auth_refs)

    def test_mcp_name_collision_is_rejected(self):
        from runtime.config import _merge_mcp_servers

        with self.assertRaisesRegex(RuntimeError, 'MCP 服务名称冲突'):
            _merge_mcp_servers({'capability_ops': object()}, {'capability_ops': object()})

    async def test_loaded_pack_is_cached_for_worker_lifetime_and_supports_relative_imports(self):
        from capability_packs.registry import load_pack

        with tempfile.TemporaryDirectory() as temp:
            packs = Path(temp)
            pack = create_pack(packs, [operation()], '''
                async def calculate(context, args):
                    from .services import Result
                    return {'answer': Result(args['value']).value}
            ''')
            (pack / 'services.py').write_text(
                'from dataclasses import dataclass\n@dataclass\nclass Result:\n    value: str\n', encoding='utf-8')
            with patch('capability_packs.registry.PACK_ROOT', packs):
                loaded = load_pack('demo-capability')
                self.assertEqual(await loaded.operations[0].execute(None, {'value': 'ok'}), {'answer': 'ok'})
                self.assertIs(load_pack('demo-capability'), loaded)
                (pack / 'operations.py').write_text('async def calculate(context, args): return {}', encoding='utf-8')
                self.assertIs(load_pack('demo-capability'), loaded)

    def test_schema_rejects_network_references(self):
        from runtime.capability_operations import manifest_pack

        for keyword in ('$ref', '$dynamicRef', '$id'):
            spec = operation()
            spec['inputSchema']['properties']['value'] = {keyword: 'https://example.invalid/schema'}
            with self.subTest(keyword=keyword), self.assertRaises(RuntimeError):
                manifest_pack({'ref': 'demo-capability', 'operations': [spec]}, 'demo-capability')

    async def test_package_entry_can_import_operations_without_running_them_twice(self):
        from capability_packs.registry import load_pack

        with tempfile.TemporaryDirectory() as temporary:
            packs = Path(temporary)
            directory = create_pack(packs, [operation()], '''
                from . import services
                services.loads += 1
                async def calculate(context, args):
                    from . import calculate as public_calculate
                    return {'answer': str(services.loads), 'same': public_calculate is calculate}
            ''')
            (directory / 'services.py').write_text('loads = 0\n', encoding='utf-8')
            (directory / '__init__.py').write_text('from .operations import calculate\n', encoding='utf-8')
            with patch('capability_packs.registry.PACK_ROOT', packs):
                pack = load_pack('demo-capability')
                self.assertEqual(await pack.operations[0].execute(None, {}), {'answer': '1', 'same': True})

    async def test_schema_distinguishes_business_data_from_schema_keywords(self):
        from runtime.capability_operations import build_operation_server

        spec = operation()
        literal = {'$id': 'business-id', '$ref': 'https://example.invalid/value'}
        spec['inputSchema']['properties'] = {
            'value': {'const': literal}, '$id': {'$ref': '#/$defs/text'},
        }
        spec['inputSchema']['$defs'] = {'text': {'type': 'string'}}
        with tempfile.TemporaryDirectory() as temporary:
            packs = Path(temporary)
            create_pack(packs, [spec], "async def calculate(context, args): return {'answer': args['$id']}")
            with patch('capability_packs.registry.PACK_ROOT', packs), \
                 patch('runtime.capability_operations.create_sdk_mcp_server', side_effect=lambda name, **kw: kw):
                _, server, _ = build_operation_server({'ref': 'demo-capability', 'operation_refs': ['calculate']},
                    {'run_id': 'run-schema'})
            result = await server['tools'][0].handler({'value': literal, '$id': 'ok'})
            self.assertEqual(json.loads(result['content'][0]['text']), {'answer': 'ok'})

    async def test_schema_reference_into_literal_data_cannot_retrieve_remote_schema(self):
        from runtime.capability_operations import build_operation_server

        spec = operation()
        spec['inputSchema'].update(examples=[{'$ref': 'https://example.invalid/schema'}],
                                   allOf=[{'$ref': '#/examples/0'}])
        with tempfile.TemporaryDirectory() as temporary:
            packs = Path(temporary)
            create_pack(packs, [spec], "async def calculate(context, args): return {'answer': 'never'}")
            with patch('capability_packs.registry.PACK_ROOT', packs), \
                 patch('runtime.capability_operations.create_sdk_mcp_server', side_effect=lambda name, **kw: kw):
                _, server, _ = build_operation_server({'ref': 'demo-capability', 'operation_refs': ['calculate']},
                    {'run_id': 'run-schema'})
            with patch('urllib.request.urlopen') as retrieve:
                result = await server['tools'][0].handler({'value': 'ok'})
                self.assertTrue(result['isError'])
                retrieve.assert_not_called()

    def test_operation_preview_is_static_and_contains_only_selected_schemas(self):
        from runtime.asset_management import _preview
        from runtime.capabilities import capability_entry

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            directory = self._capability(root / 'capabilities', operations=['calculate'])
            create_pack(root / 'packs', [operation(), operation(ref='hidden')],
                        "raise RuntimeError('preview must not execute code')")
            with patch('runtime.capabilities.CAPABILITIES_ROOT', directory.parent), \
                 patch('capability_packs.registry.PACK_ROOT', root / 'packs'):
                entry = capability_entry(directory, skills_root=root / 'skills')
                view = _preview(entry)
            self.assertEqual([item['ref'] for item in view['operations']], ['calculate'])
            self.assertEqual(view['operations'][0]['toolName'], 'mcp__capability_ops__calculate')
            self.assertEqual(view['operations'][0]['inputSchema'], operation()['inputSchema'])
            self.assertEqual(view['operations'][0]['outputSchema'], operation()['outputSchema'])

    async def test_sync_operations_enforce_json_and_schema_boundaries(self):
        from runtime.capability_operations import build_operation_server

        with tempfile.TemporaryDirectory() as temporary:
            packs = Path(temporary)
            create_pack(packs, [operation()], '''
                def calculate(context, args):
                    if args['value'] == 'nan':
                        return {'answer': float('nan')}
                    return {'answer': context.run_id + ':' + args['value']}
            ''')
            with patch('capability_packs.registry.PACK_ROOT', packs), \
                 patch('runtime.capability_operations.create_sdk_mcp_server', side_effect=lambda name, **kw: kw):
                _, server, _ = build_operation_server({'ref': 'demo-capability',
                    'operation_refs': ['calculate']},
                    {'run_id': 'run-sync'})
            handler = server['tools'][0].handler
            result = await handler({'value': 'ok'})
            self.assertEqual(json.loads(result['content'][0]['text']), {'answer': 'run-sync:ok'})
            for args, code in (({'value': float('nan')}, 'PARAMETERS_INVALID'),
                               ({'value': 'nan'}, 'RESULT_INVALID')):
                with self.subTest(code=code):
                    result = await handler(args)
                    self.assertEqual(json.loads(result['content'][0]['text'])['error']['code'], code)

    async def test_build_options_authorizes_only_declared_operation_for_agent_and_direct(self):
        from runtime.capabilities import capability_entry
        from runtime.claude_sdk import ClientTurnPolicy
        from runtime.config import build_options

        with tempfile.TemporaryDirectory() as temp:
            temp = Path(temp)
            capabilities = temp / 'capabilities'
            entry_dir = self._capability(capabilities, operations=['calculate'])
            packs = temp / 'packs'
            create_pack(packs, [operation(), operation(ref='hidden', handler='hidden')], '''
                async def calculate(context, args): return {'answer': 'ok'}
                async def hidden(context, args): return {'answer': 'private'}
            ''')
            with patch('runtime.capabilities.CAPABILITIES_ROOT', capabilities), \
                 patch('capability_packs.registry.PACK_ROOT', packs):
                entry = capability_entry(entry_dir, skills_root=temp / 'skills')
                payload = {'capability_ref': 'demo-capability', 'run_id': 'run-1',
                           'credentials': {'platformBearer': 'must-not-leak'},
                           '_execution_entry': {'capability': entry}}
                options = build_options(payload, turn_policy=ClientTurnPolicy())

            self.assertEqual(list(options.mcp_servers), ['capability_ops'])
            self.assertEqual(options.allowed_tools, ['mcp__capability_ops__calculate'])
            policy = ClientTurnPolicy()
            policy.bind(options)
            allowed = await policy.authorize({'tool_name': 'mcp__capability_ops__calculate'}, None, {})
            denied = await policy.authorize({'tool_name': 'mcp__capability_ops__hidden'}, None, {})
            self.assertEqual(allowed, {})
            self.assertEqual(denied['hookSpecificOutput']['permissionDecision'], 'deny')

            entry['execution']['mode'] = 'direct'
            with patch('capability_packs.registry.PACK_ROOT', packs):
                direct = build_options({'capability_ref': 'demo-capability', 'run_id': 'run-2',
                                        '_execution_entry': {'capability': entry}})
            self.assertEqual(direct.tools, [])
            self.assertTrue(direct.strict_mcp_config)
            self.assertEqual(direct.allowed_tools, ['mcp__capability_ops__calculate'])

    async def test_operation_can_use_authorized_data_service_without_exposing_data_tools(self):
        from unittest.mock import AsyncMock, MagicMock
        from runtime.capabilities import capability_entry
        from runtime.config import build_options

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            capabilities = root / 'capabilities'
            directory = self._capability(capabilities, operations=['calculate'])
            manifest_path = directory / 'capability.json'
            manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
            manifest['data'] = {'access': 'required', 'sourceRefs': ['schoolDoubleHigh']}
            manifest_path.write_text(json.dumps(manifest), encoding='utf-8')
            create_pack(root / 'packs', [operation()], '''
                async def calculate(context, args):
                    sources = await context.data.list_data_sources()
                    return {'answer': sources[0]['sourceKey']}
            ''')
            services = MagicMock()
            services.call = AsyncMock(return_value=[{'sourceKey': 'schoolDoubleHigh'}])
            with patch('runtime.capabilities.CAPABILITIES_ROOT', capabilities), \
                 patch('capability_packs.registry.PACK_ROOT', root / 'packs'), \
                 patch('runtime.capability_operations.create_sdk_mcp_server', side_effect=lambda name, **kw: kw):
                entry = capability_entry(directory, skills_root=root / 'skills')
                options = build_options({'capability_ref': 'demo-capability', 'run_id': 'run-data',
                    '_execution_entry': {'capability': entry}}, data_services=services)
                self.assertEqual(options.allowed_tools, ['mcp__capability_ops__calculate'])
                result = await options.mcp_servers['capability_ops']['tools'][0].handler({'value': 'ok'})
                self.assertEqual(json.loads(result['content'][0]['text']), {'answer': 'schoolDoubleHigh'})
                services.call.assert_awaited_once_with(services.current().list_data_sources)

                # 未提供调用入口或来源时，仍拒绝无效的数据资产声明。
                for fields in ({'operationRefs': []}, {'data': {'access': 'required', 'sourceRefs': []}}):
                    manifest_path.write_text(json.dumps({**manifest, **fields}), encoding='utf-8')
                    with self.subTest(fields=fields), self.assertRaises(RuntimeError):
                        capability_entry(directory, skills_root=root / 'skills')

    async def test_operation_can_use_declared_internal_service_without_exposing_it(self):
        from types import SimpleNamespace
        from runtime.capability_operations import build_operation_server

        with tempfile.TemporaryDirectory() as temporary:
            packs = Path(temporary) / 'packs'
            create_pack(packs, [operation()], '''
                async def calculate(context, args):
                    service = context.services.require('example')
                    return {'answer': await service.calculate(args['value'])}
            ''')
            service = SimpleNamespace(calculate=__import__('unittest').mock.AsyncMock(return_value='service-result'))
            tool_services = SimpleNamespace(services={'example': service})
            with patch('capability_packs.registry.PACK_ROOT', packs), \
                 patch('runtime.capability_operations.create_sdk_mcp_server', side_effect=lambda name, **kwargs: kwargs):
                _, server, _ = build_operation_server(
                    {'ref': 'demo-capability', 'operation_refs': ['calculate'],
                     'service_refs': ['example']},
                    {'run_id': 'run-service', 'operation_services': tool_services})
                result = await server['tools'][0].handler({'value': 'ok'})

            self.assertEqual(json.loads(result['content'][0]['text']), {'answer': 'service-result'})
            service.calculate.assert_awaited_once_with('ok')
            self.assertEqual(server['tools'][0].name, 'calculate')

    async def test_cancelled_operations_finish_before_next_run_can_start(self):
        from capability_packs.registry import load_pack
        from runtime.capability_operations import build_operation_server
        from runtime.claude_sdk import SDKExecutionError, SDKTimeoutError, SDKToolScope

        for synchronous in (False, True):
            with self.subTest(synchronous=synchronous), tempfile.TemporaryDirectory() as temporary:
                packs = Path(temporary)
                code = '''
                    import asyncio
                    started, finished = asyncio.Event(), asyncio.Event()
                    async def calculate(context, args):
                        started.set()
                        try:
                            await asyncio.Event().wait()
                        finally:
                            finished.set()
                ''' if not synchronous else '''
                    import threading
                    started, finished, release = (threading.Event() for _ in range(3))
                    def calculate(context, args):
                        started.set()
                        try:
                            release.wait(3)
                            return {'answer': 'late result'}
                        finally:
                            finished.set()
                '''
                create_pack(packs, [operation()], code)
                scope = SDKToolScope()
                scope.start()
                with patch('capability_packs.registry.PACK_ROOT', packs), scope.capture(), \
                     patch('runtime.capability_operations.create_sdk_mcp_server', side_effect=lambda name, **kw: kw):
                    loaded = load_pack('demo-capability')
                    state = loaded.operations[0].execute.__globals__
                    _, server, _ = build_operation_server({'ref': 'demo-capability',
                        'operation_refs': ['calculate']}, {'run_id': 'run-cancel'})
                call = asyncio.create_task(server['tools'][0].handler({'value': 'ok'}))
                try:
                    if synchronous:
                        self.assertTrue(await asyncio.to_thread(state['started'].wait, 2))
                    else:
                        await asyncio.wait_for(state['started'].wait(), 2)
                    scope.stop(cancel=True)
                    if synchronous:
                        with self.assertRaises(SDKTimeoutError):
                            await scope.drain(timeout_ms=10)
                        with self.assertRaises(SDKExecutionError):
                            scope.start()
                        self.assertFalse(state['finished'].is_set())
                    else:
                        await scope.drain(timeout_ms=1000)
                        self.assertTrue(state['finished'].is_set())
                finally:
                    if synchronous:
                        state['release'].set()
                    scope.stop(cancel=True)
                    await scope.drain(timeout_ms=1000)
                    result = await call
                self.assertTrue(state['finished'].is_set())
                self.assertTrue(result['isError'])
                scope.start()
                self.assertTrue((await server['tools'][0].handler({'value': 'ok'}))['isError'])
                scope.stop()


if __name__ == '__main__':
    unittest.main()
