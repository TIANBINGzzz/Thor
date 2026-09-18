import json
from io import BytesIO
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import httpx
from PIL import Image

from tools.images import generate_image
from runtime.config import agent_environment, worker_environment, build_options


class ImageToolTests(unittest.IsolatedAsyncioTestCase):
    async def test_generate_and_reference_use_same_api_without_forwarding_key_to_download(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            png = BytesIO()
            Image.new('RGB', (20, 15), 'green').save(png, format='PNG')
            reference = root / 'reference.png'
            reference.write_bytes(png.getvalue())
            requests = []

            def respond(request):
                requests.append(request)
                if request.method == 'POST':
                    return httpx.Response(200, json={'data': [{'url': 'https://images.test/result.png'}]})
                return httpx.Response(200, content=png.getvalue())

            client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
            with patch('tools.images.httpx.AsyncClient', return_value=client):
                result = await generate_image('示意图', 'result.png', base_dir=root,
                    base_url='https://api.test/v1', api_key='secret', reference_paths=['reference.png'])
            self.assertEqual(result['model'], 'qwen-image-3.0')
            self.assertEqual((result['width'], result['height']), (20, 15))
            self.assertEqual(requests[0].url.path, '/v1/images/generations')
            self.assertEqual(requests[0].headers['Authorization'], 'Bearer secret')
            body = json.loads(requests[0].content)
            self.assertTrue(body['image'][0].startswith('data:image/png;base64,'))
            self.assertFalse(body['prompt_extend'])
            self.assertNotIn('Authorization', requests[1].headers)
            self.assertEqual(reference.read_bytes(), png.getvalue())
            with self.assertRaises(FileExistsError):
                await generate_image('x', 'result.png', base_dir=root, base_url='x', api_key='secret')
            with self.assertRaises(ValueError):
                await generate_image('x', '../outside.png', base_dir=root, base_url='x', api_key='secret')

    async def test_failed_generation_does_not_leak_body_or_retry(self):
        with tempfile.TemporaryDirectory() as root:
            count = 0

            def respond(request):
                nonlocal count
                count += 1
                return httpx.Response(401, json={'error': {'code': 'InvalidApiKey', 'message': 'secret-value'}})

            client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
            with patch('tools.images.httpx.AsyncClient', return_value=client), self.assertRaises(RuntimeError) as caught:
                await generate_image('x', 'result.png', base_dir=root, base_url='https://api.test/v1', api_key='secret')
            self.assertIn('InvalidApiKey', str(caught.exception))
            self.assertNotIn('secret-value', str(caught.exception))
            self.assertEqual(count, 1)
            self.assertFalse((Path(root) / 'result.png').exists())

    def test_configuration_stays_in_worker_and_qa_cannot_mount_images(self):
        values = {'CCSDK_IMAGE_BASE_URL': 'https://api.test/v1', 'CCSDK_IMAGE_API_KEY': 'image-secret'}
        with patch.dict('os.environ', values, clear=True):
            self.assertNotIn('CCSDK_IMAGE_API_KEY', agent_environment())
            self.assertEqual(worker_environment()['CCSDK_IMAGE_API_KEY'], 'image-secret')
            options = build_options({'capability_ref': 'conversation'})
            self.assertIn('images', options.mcp_servers)
            self.assertNotIn('image-secret', options.system_prompt['append'])
            qa = build_options({'workflow_name': 'double-high-qa', 'capability_ref': 'national-excellence-data-qa'})
            self.assertNotIn('images', qa.mcp_servers)
