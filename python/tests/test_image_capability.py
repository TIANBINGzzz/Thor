"""图像能力入口、SDK工具装配及多图片交稿回归。"""
import asyncio
from io import BytesIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import httpx
from PIL import Image
from fastapi.testclient import TestClient

import server
from runtime.capabilities import resolve_capability
from runtime.config import build_options
from runtime.protocol import AgentRunRequest
from runtime.run_store import RunStore
from runtime.artifact_delivery import ArtifactDelivery
from tools.images import generate_image
from tools.artifacts import create_artifact_server


class ImageCapabilityTests(unittest.TestCase):
    def test_image_defaults_reuse_general_key_and_workspace_url(self):
        with patch.dict('os.environ', {
                'ANTHROPIC_AUTH_TOKEN': 'shared-private-key',
                'ANTHROPIC_BASE_URL': 'https://workspace.cn-beijing.maas.aliyuncs.com/apps/anthropic'}, clear=True), \
                patch('tools.images.create_image_server', return_value={}) as create:
            options = build_options({'capability_ref': 'image-generation'})
        self.assertEqual(create.call_args.kwargs['api_key'], 'shared-private-key')
        self.assertEqual(create.call_args.kwargs['base_url'],
                         'https://workspace.cn-beijing.maas.aliyuncs.com/compatible-mode/v1')
        self.assertNotIn('shared-private-key', options.system_prompt['append'])

    def test_unknown_provider_is_not_guessed_as_image_endpoint(self):
        with patch.dict('os.environ', {'ANTHROPIC_AUTH_TOKEN': 'shared-private-key',
                'ANTHROPIC_BASE_URL': 'https://provider.test/apps/anthropic'}, clear=True):
            with self.assertRaisesRegex(RuntimeError, '能力必需工具未配置'):
                build_options({'capability_ref': 'image-generation'})

    def test_catalog_and_reference_input(self):
        with TestClient(server.app) as client:
            items = client.get('/internal/v1/capabilities').json()['capabilities']
        item = next(item for item in items if item['capabilityRef'] == 'image-generation')
        self.assertEqual(item['name'], '图像生成')
        self.assertTrue(item['supportsAttachments'])
        self.assertIsNone(resolve_capability('image-generation').workflow_ref)
        request = AgentRunRequest.from_dict({'protocol': 'agent-run/v1', 'runId': 'image-test',
            'messageId': 'msg-test', 'businessSessionId': 'session-test',
            'capabilityRef': 'image-generation', 'input': {'text': '参考此图生成两张插画',
            'attachmentRefs': [{'fileId': 'reference-1', 'purpose': 'input'}]}})
        self.assertEqual(request.input.attachment_refs[0].file_id, 'reference-1')

    def test_sdk_mounts_generation_and_publication_with_private_credentials(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict('os.environ', {
                'CCSDK_IMAGE_BASE_URL': 'https://api.test/v1',
                'CCSDK_IMAGE_API_KEY': 'private-image-key'}, clear=True):
            options = build_options({'capability_ref': 'image-generation',
                'session_directory': directory, 'work_directory': directory,
                'deliverables_directory': str(Path(directory) / 'output')})
        self.assertTrue({'images', 'artifacts'} <= set(options.mcp_servers))
        self.assertIn('mcp__images__generate', options.allowed_tools)
        self.assertIn('mcp__artifacts__publish_file', options.allowed_tools)
        self.assertIn('逐张', options.system_prompt['append'])
        self.assertNotIn('private-image-key', options.system_prompt['append'])

    def test_missing_image_credentials_fails_explicitly(self):
        with patch.dict('os.environ', {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, '能力必需工具未配置'):
                build_options({'capability_ref': 'image-generation'})

    def test_three_generated_pngs_publish_independently(self):
        async def exercise(root):
            events = []
            with patch('tools.artifacts.create_sdk_mcp_server', side_effect=lambda *args, **kw: kw):
                publisher = create_artifact_server(root, root, root / 'output', on_published=events.append)
            receipts = []
            for index, color in enumerate(('red', 'green', 'blue')):
                png = BytesIO()
                Image.new('RGB', (32, 24), color).save(png, format='PNG')
                def respond(request):
                    if request.method == 'POST':
                        return httpx.Response(200, json={'data': [{'url': 'https://images.test/output'}]})
                    return httpx.Response(200, content=png.getvalue())
                client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
                with patch('tools.images.httpx.AsyncClient', return_value=client):
                    generated = await generate_image('校园插画', f'image-{index}.png',
                        base_dir=root, base_url='https://api.test/v1', api_key='private-key')
                receipt = await publisher['tools'][0].handler({
                    'source_path': generated['path'], 'file_name': f'image-{index}.png'})
                receipts.append(json.loads(receipt['content'][0]['text']))
            self.assertEqual(len({r['artifactId'] for r in receipts}), 3)
            self.assertEqual(len(events), 3)
            for receipt in receipts:
                self.assertNotIn('status', receipt)
                with Image.open(root / 'output' / receipt['artifactId'] / 'content') as image:
                    self.assertEqual(image.format, 'PNG')
                    self.assertEqual(image.size, (32, 24))
            config = root / 'databases.json'
            self.enterContext(patch('runtime.nacos_config.fetch_config', side_effect=lambda env, **kw:
                json.loads(config.read_text(encoding='utf-8'))))
            config.write_text(json.dumps({'fileService': {'baseUrl': 'https://files.test',
                'domainName': 'routing.test', 'remoteUrl': 'https://public.test'}}))
            store = RunStore(':memory:')
            store.create_run('images-run', tenant_id='tenant', user_id='user')
            uploaded = []
            states = []
            def upload(request):
                uploaded.append(request)
                self.assertIn(b'Content-Type: image/png', request.content)
                size = next(r['size'] for r in receipts if r['name'].encode() in request.content)
                return httpx.Response(200, json={'state': 200, 'success': True, 'data': {
                    'id': f'file-{len(uploaded)}', 'fileName': 'image.png', 'fileSuffix': 'png',
                    'url': 'private/image.png', 'fileSize': size}})
            async def notify(event):
                states.append(event)
            delivery = ArtifactDelivery(store, root / 'archive', notify,
                env={'CCSDK_DATABASES_FILE': str(config)}, transport=httpx.MockTransport(upload))
            try:
                for receipt in receipts:
                    await delivery.accept('images-run', root / 'output', receipt['artifactId'])
                await delivery.wait('images-run')
                files = delivery.list('images-run')
                self.assertEqual(len(files), 3)
                self.assertTrue(all(f['status'] == 'ready' for f in files))
                self.assertEqual(len({f['fileId'] for f in files}), 3)
                self.assertEqual(sum(e['type'] == 'artifact.ready' for e in states), 3)
                ready = [e['payload'] for e in states if e['type'] == 'artifact.ready']
                self.assertEqual({e['fileId'] for e in ready}, {f['fileId'] for f in files})
                replay = [e['payload'] for e in store.events_after('images-run') if e['type'] == 'artifact.ready']
                self.assertEqual(replay, ready)
                self.assertFalse(any('private/image.png' in json.dumps(e) for e in ready))
            finally:
                await delivery.close()
                store.close()
        with tempfile.TemporaryDirectory() as directory:
            asyncio.run(exercise(Path(directory)))
