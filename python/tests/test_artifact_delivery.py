"""文件上传状态、请求边界与持久化恢复的契约测试。"""

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx

from runtime.run_store import RunStore
from tools.artifacts import publish_artifact


class ArtifactDeliveryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from runtime.artifact_delivery import ArtifactDelivery
        delays = patch('runtime.artifact_delivery.RETRY_DELAYS', (0, 0), create=True)
        delays.start()
        self.addCleanup(delays.stop)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = RunStore(self.root / 'runs.sqlite3')
        self.addCleanup(self.store.close)
        self.store.create_run('run_01', tenant_id='tenant', user_id='user')
        self.config = self.root / 'databases.json'
        self.enterContext(patch('runtime.file_service._fetch_config',
            side_effect=lambda env, **kw: json.loads(self.config.read_text(encoding='utf-8'))))
        self.config.write_text(json.dumps({'version': 1, 'sources': {}, 'fileService': {
            'baseUrl': 'https://files.example.test', 'domainName': 'routing.example.test',
            'remoteUrl': 'https://public.example.test',
        }}), encoding='utf-8')
        self.requests = []
        self.reply = lambda request: httpx.Response(200, json={'state': 200, 'success': True, 'data': {
            'id': 'remote_01', 'fileName': '报告.txt', 'fileSize': 5, 'fileSuffix': 'txt',
            'url': 'stringfast/private-object.txt',
        }})
        def handler(request):
            self.requests.append(request)
            return self.reply(request)
        self.events = []
        async def notify(event):
            self.events.append(event)
        self.delivery = ArtifactDelivery(self.store, self.root / 'archive', notify,
            env={'CCSDK_DATABASES_FILE': str(self.config)}, transport=httpx.MockTransport(handler))
        self.addAsyncCleanup(self.delivery.close)
        self.work = self.root / 'session' / '.work'
        self.work.mkdir(parents=True)
        self.spool = self.root / 'session' / '.deliverables'
        (self.work / 'draft.txt').write_bytes(b'hello')

    def publish(self):
        return publish_artifact('draft.txt', '报告.txt', self.work, self.spool, self.work.parent)

    async def test_stream_upload_and_idempotent_registration(self):
        item = self.publish()
        await self.delivery.accept('run_01', self.spool, item['artifactId'])
        await self.delivery.wait('run_01')
        await self.delivery.accept('run_01', self.spool, item['artifactId'])
        await self.delivery.wait('run_01')
        self.assertEqual(len(self.requests), 1)
        request = self.requests[0]
        self.assertEqual(str(request.url), 'https://files.example.test/fwk_manage_service/sys_attachment/ai/upload/')
        self.assertEqual(request.headers['domain-name'], 'routing.example.test')
        self.assertEqual(request.headers['remote-url'], 'https://public.example.test')
        self.assertNotIn('authorization', request.headers)
        self.assertIn(b'name="file"', request.content)
        self.assertIn('报告.txt'.encode(), request.content)
        self.assertIn(b'hello', request.content)
        self.assertEqual([e['type'] for e in self.events], ['artifact.pending', 'artifact.uploading', 'artifact.ready'])
        files = self.delivery.list('run_01')
        self.assertEqual(files[0]['fileId'], 'remote_01')
        self.assertEqual(files[0]['status'], 'ready')
        self.assertNotIn('stringfast', json.dumps(files))
        self.assertNotIn(str(self.root), json.dumps(files))
        self.assertEqual(self.delivery.list('other_run'), [])
        self.assertEqual(self.delivery.path('run_01', item['artifactId']).read_bytes(), b'hello')
        self.assertIsNone(self.delivery.path('other_run', item['artifactId']))
        self.assertEqual([e['type'] for e in self.store.events_after('run_01')],
                         ['artifact.pending', 'artifact.uploading', 'artifact.ready'])

    async def test_uncertain_timeout_does_not_blindly_retry(self):
        def timeout(request):
            raise httpx.ReadTimeout('private-url-and-token', request=request)
        self.reply = timeout
        item = self.publish()
        await self.delivery.accept('run_01', self.spool, item['artifactId'])
        await self.delivery.wait('run_01')
        await self.delivery.accept('run_01', self.spool, item['artifactId'])
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(self.delivery.list('run_01')[0]['status'], 'unknown')
        self.assertNotIn('private-url-and-token', json.dumps(self.events))

    async def test_business_failure_is_not_ready(self):
        self.reply = lambda request: httpx.Response(200, json={'state': 500, 'success': False, 'message': 'private'})
        item = self.publish()
        await self.delivery.accept('run_01', self.spool, item['artifactId'])
        await self.delivery.wait('run_01')
        self.assertEqual(self.delivery.list('run_01')[0]['status'], 'failed')
        self.assertEqual(self.events[-1]['type'], 'artifact.failed')
        self.assertNotIn('private', json.dumps(self.events))
        self.assertEqual(len(self.requests), 3)
        self.assertEqual([e['type'] for e in self.events],
                         ['artifact.pending', 'artifact.uploading', 'artifact.failed'])

    async def test_missing_configuration_never_uses_an_implicit_host(self):
        self.config.write_text('{"version": 1, "sources": {}}')
        item = self.publish()
        await self.delivery.accept('run_01', self.spool, item['artifactId'])
        await self.delivery.wait('run_01')
        self.assertEqual(self.requests, [])
        self.assertEqual(self.delivery.list('run_01')[0]['error'], 'file_service_not_configured')

    async def test_nacos_failure_does_not_upload_using_previous_settings(self):
        from runtime.file_service import FileServiceError
        item = self.publish()
        with patch('runtime.file_service._fetch_config',
                   side_effect=FileServiceError('file_service_nacos_unavailable')):
            await self.delivery.accept('run_01', self.spool, item['artifactId'])
            await self.delivery.wait('run_01')
        self.assertEqual(self.requests, [])
        self.assertEqual(self.delivery.list('run_01')[0]['error'], 'file_service_nacos_unavailable')

    async def test_snapshot_corruption_rejected_before_upload(self):
        item = self.publish()
        (self.spool / item['artifactId'] / 'content').write_bytes(b'changed')
        with self.assertRaises(ValueError):
            await self.delivery.accept('run_01', self.spool, item['artifactId'])
        self.assertEqual(self.requests, [])

    async def test_redirect_is_not_followed(self):
        self.reply = lambda request: httpx.Response(307, headers={'location': 'https://other.example.test'})
        item = self.publish()
        await self.delivery.accept('run_01', self.spool, item['artifactId'])
        await self.delivery.wait('run_01')
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(self.delivery.list('run_01')[0]['status'], 'failed')

    async def test_notification_failure_does_not_change_committed_upload_result(self):
        async def broken(event):
            raise RuntimeError('subscriber unavailable')
        self.delivery.notify = broken
        item = self.publish()
        await self.delivery.accept('run_01', self.spool, item['artifactId'])
        await self.delivery.wait('run_01')
        self.assertEqual(self.delivery.list('run_01')[0]['status'], 'ready')
        self.assertEqual(len(self.requests), 1)

    async def test_recovery_does_not_resend_uncertain_upload(self):
        item = self.publish()
        record = self.delivery._snapshot('run_01', self.spool, item['artifactId'])
        await self.delivery._state(record, 'uploading')
        await self.delivery.recover()
        await self.delivery.wait('run_01')
        self.assertEqual(self.requests, [])
        self.assertEqual(self.delivery.list('run_01')[0]['status'], 'unknown')

    async def test_recovery_resumes_pending_and_keeps_same_filename_versions(self):
        first, second = self.publish(), self.publish()
        for item in (first, second):
            record = self.delivery._snapshot('run_01', self.spool, item['artifactId'])
            await self.delivery._state(record, 'pending')
        await self.delivery.recover()
        await self.delivery.wait('run_01')
        self.assertEqual(len(self.requests), 2)
        self.assertEqual(len(self.delivery.list('run_01')), 2)
        self.assertTrue(all(i['status'] == 'ready' for i in self.delivery.list('run_01')))
        self.store.create_run('run_02', tenant_id='tenant', user_id='user')
        with self.assertRaisesRegex(ValueError, 'owner'):
            await self.delivery.accept('run_02', self.spool, first['artifactId'])

    async def test_invalid_success_response_is_unknown(self):
        for data in ({}, {'id': 'file_1', 'fileName': 'x', 'fileSize': 6, 'fileSuffix': 'txt', 'url': 'x'}):
            self.reply = lambda request: httpx.Response(200, json={'state': 200, 'success': True, 'data': data})
            item = self.publish()
            await self.delivery.accept('run_01', self.spool, item['artifactId'])
            await self.delivery.wait('run_01')
            self.assertEqual(self.store.artifact(item['artifactId'])['status'], 'unknown')

    async def test_http_500_retries_same_file_then_succeeds(self):
        success = self.reply
        self.reply = lambda request: httpx.Response(500) if len(self.requests) < 3 else success(request)
        item = self.publish()
        await self.delivery.accept('run_01', self.spool, item['artifactId'])
        await self.delivery.wait('run_01')
        file = self.delivery.list('run_01')[0]
        self.assertEqual(file['artifactId'], item['artifactId'])
        self.assertEqual(file['status'], 'ready')
        self.assertEqual(file['fileId'], 'remote_01')
        self.assertNotIn('retryable', file)
        self.assertNotIn('error', file)
        self.assertEqual(len(self.requests), 3)
        self.assertTrue(all(b'hello' in r.content for r in self.requests))
        self.assertEqual([e['type'] for e in self.events],
                         ['artifact.pending', 'artifact.uploading', 'artifact.ready'])

    async def test_concurrent_registrations_share_automatic_retries(self):
        item = self.publish()
        self.reply = lambda request: httpx.Response(500)
        await asyncio.gather(*(self.delivery.accept('run_01', self.spool, item['artifactId']) for _ in range(5)))
        await self.delivery.wait('run_01')
        self.assertEqual(len(self.requests), 3)
        self.assertEqual(self.delivery.list('run_01')[0]['error'], 'file_upload_server_error')
        self.assertEqual([e['type'] for e in self.events],
                         ['artifact.pending', 'artifact.uploading', 'artifact.failed'])

    async def test_connect_error_retries_but_explicit_rejection_does_not(self):
        def unreachable(request):
            raise httpx.ConnectError('private', request=request)
        self.reply = unreachable
        item = self.publish()
        await self.delivery.accept('run_01', self.spool, item['artifactId'])
        await self.delivery.wait('run_01')
        self.assertEqual(len(self.requests), 3)
        self.assertEqual(self.store.artifact(item['artifactId'])['error'], 'file_service_unreachable')
        for response in (httpx.Response(403), httpx.Response(200, json={'state': 403, 'success': False})):
            self.requests.clear()
            self.reply = lambda request: response
            item = self.publish()
            await self.delivery.accept('run_01', self.spool, item['artifactId'])
            await self.delivery.wait('run_01')
            self.assertEqual(len(self.requests), 1)
            self.assertEqual(self.store.artifact(item['artifactId'])['error'], 'file_upload_rejected')

    async def test_size_check_happens_before_network(self):
        item = self.publish()
        config = json.loads(self.config.read_text())
        config['fileService']['maxFileBytes'] = 1
        self.config.write_text(json.dumps(config))
        await self.delivery.accept('run_01', self.spool, item['artifactId'])
        await self.delivery.wait('run_01')
        self.assertEqual(self.store.artifact(item['artifactId'])['error'], 'artifact_too_large')
        self.assertEqual(self.requests, [])

    async def test_total_deadline_includes_retry_waits(self):
        config = json.loads(self.config.read_text())
        config['fileService']['timeoutSeconds'] = 1
        self.config.write_text(json.dumps(config))
        self.reply = lambda request: httpx.Response(500)
        with patch('runtime.artifact_delivery.RETRY_DELAYS', (5, 5), create=True):
            item = self.publish()
            await self.delivery.accept('run_01', self.spool, item['artifactId'])
            await asyncio.wait_for(self.delivery.wait('run_01'), 2)
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(self.store.artifact(item['artifactId'])['status'], 'failed')
        self.assertEqual(self.events[-1]['type'], 'artifact.failed')

    async def test_cancellation_during_backoff_stops_retries(self):
        attempted = asyncio.Event()
        def fail(request):
            attempted.set()
            return httpx.Response(500)
        self.reply = fail
        with patch('runtime.artifact_delivery.RETRY_DELAYS', (5, 5), create=True):
            item = self.publish()
            await self.delivery.accept('run_01', self.spool, item['artifactId'])
            await asyncio.wait_for(attempted.wait(), 2)
            await self.delivery.close()
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(self.store.artifact(item['artifactId'])['status'], 'failed')
