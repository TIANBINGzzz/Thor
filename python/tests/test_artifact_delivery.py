"""文件上传状态、请求边界与持久化恢复的契约测试。"""

import asyncio
import json
import tempfile
import unittest
from pathlib import Path

import httpx

from runtime.run_store import RunStore
from tools.artifacts import publish_artifact


class ArtifactDeliveryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from runtime.artifact_delivery import ArtifactDelivery
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = RunStore(self.root / 'runs.sqlite3')
        self.addCleanup(self.store.close)
        self.store.create_run('run_01', tenant_id='tenant', user_id='user')
        self.config = self.root / 'databases.json'
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

    async def test_missing_configuration_never_uses_an_implicit_host(self):
        self.config.write_text('{"version": 1, "sources": {}}')
        item = self.publish()
        await self.delivery.accept('run_01', self.spool, item['artifactId'])
        await self.delivery.wait('run_01')
        self.assertEqual(self.requests, [])
        self.assertEqual(self.delivery.list('run_01')[0]['error'], 'file_service_not_configured')

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

    async def test_retry_uploads_same_snapshot_and_clears_previous_error(self):
        self.assertTrue(callable(getattr(self.delivery, 'retry', None)), '缺少文件上传重试实现')
        success = self.reply
        self.reply = lambda request: httpx.Response(403)
        item = self.publish()
        await self.delivery.accept('run_01', self.spool, item['artifactId'])
        await self.delivery.wait('run_01')
        self.assertTrue(self.delivery.list('run_01')[0]['retryable'])
        self.store.update_status('run_01', 'succeeded')
        self.reply = success
        file, status = await self.delivery.retry('run_01', item['artifactId'])
        self.assertEqual(status, 202)
        self.assertEqual(file['status'], 'pending')
        self.assertNotIn('error', file)
        await self.delivery.wait('run_01')
        file = self.delivery.list('run_01')[0]
        self.assertEqual(file['artifactId'], item['artifactId'])
        self.assertEqual(file['status'], 'ready')
        self.assertEqual(file['fileId'], 'remote_01')
        self.assertFalse(file['retryable'])
        self.assertNotIn('error', file)
        self.assertEqual(self.store.get_run('run_01')['status'], 'succeeded')
        self.assertEqual(len(self.requests), 2)
        self.assertEqual((await self.delivery.retry('run_01', item['artifactId']))[1], 200)
        self.assertEqual(len(self.requests), 2)

    async def test_concurrent_retries_share_one_upload(self):
        self.assertTrue(callable(getattr(self.delivery, 'retry', None)))
        item = self.publish()
        record = self.delivery._snapshot('run_01', self.spool, item['artifactId'])
        await self.delivery._state(record, 'failed', error='file_service_unreachable')
        started, release = asyncio.Event(), asyncio.Event()
        async def handler(request):
            self.requests.append(request)
            started.set()
            await release.wait()
            return self.reply(request)
        self.delivery.transport = httpx.MockTransport(handler)
        results = await asyncio.gather(*(self.delivery.retry('run_01', item['artifactId']) for _ in range(5)))
        self.assertTrue(all(status == 202 for _, status in results))
        await asyncio.wait_for(started.wait(), 2)
        self.assertEqual(len(self.requests), 1)
        release.set()
        await self.delivery.wait('run_01')

    async def test_retry_rejects_unknown_missing_and_damaged_files(self):
        self.assertTrue(callable(getattr(self.delivery, 'retry', None)))
        from runtime.artifact_delivery import DeliveryError
        item = self.publish()
        record = self.delivery._snapshot('run_01', self.spool, item['artifactId'])
        await self.delivery._state(record, 'unknown', error='file_upload_uncertain')
        with self.assertRaisesRegex(DeliveryError, 'artifact_retry_not_allowed'):
            await self.delivery.retry('run_01', item['artifactId'])
        with self.assertRaisesRegex(DeliveryError, 'artifact_not_found'):
            await self.delivery.retry('other_run', item['artifactId'])
        await self.delivery._state(record, 'failed', error='file_service_unreachable')
        path = self.delivery.path('run_01', item['artifactId'])
        path.write_bytes(b'other')
        with self.assertRaisesRegex(DeliveryError, 'artifact_snapshot_invalid'):
            await self.delivery.retry('run_01', item['artifactId'])
        self.assertFalse(self.delivery.list('run_01')[0]['retryable'])
        path.unlink()
        await self.delivery._state(record, 'failed', error='file_service_unreachable')
        with self.assertRaisesRegex(DeliveryError, 'artifact_snapshot_missing'):
            await self.delivery.retry('run_01', item['artifactId'])
        self.assertEqual(self.requests, [])

    async def test_retry_configuration_and_size_checks_happen_before_network(self):
        self.assertTrue(callable(getattr(self.delivery, 'retry', None)))
        from runtime.artifact_delivery import DeliveryError
        item = self.publish()
        record = self.delivery._snapshot('run_01', self.spool, item['artifactId'])
        await self.delivery._state(record, 'failed', error='file_service_unreachable')
        config = json.loads(self.config.read_text())
        config['fileService']['maxFileBytes'] = 1
        self.config.write_text(json.dumps(config))
        with self.assertRaisesRegex(DeliveryError, 'artifact_too_large'):
            await self.delivery.retry('run_01', item['artifactId'])
        self.config.unlink()
        with self.assertRaisesRegex(DeliveryError, 'file_service_not_configured'):
            await self.delivery.retry('run_01', item['artifactId'])
        self.assertEqual(self.requests, [])
