"""下载器只接收本轮附件引用和隔离目录，不接受旧 Broker 地址或凭据。"""

import inspect
from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import httpx

from runtime.file_download import (
    FileDownloader, FileDownloadConfigurationError,
    FileDownloadTimeoutError, FileDownloadUnavailableError, FileDownloadValidationError,
)
from runtime.file_service import FileServiceError
from runtime.protocol import AttachmentRef
from runtime.runtime_settings import RUNTIME_SETTINGS


class FileDownloadContractTests(unittest.TestCase):
    def test_constructor_only_exposes_download_limits_and_observers(self):
        self.assertEqual(set(inspect.signature(FileDownloader).parameters), {
            'max_bytes', 'timeout_ms', 'transport', 'event_sink', 'progress_sink',
        })

    def test_fetch_only_takes_authorized_references_and_workspace(self):
        self.assertEqual(set(inspect.signature(FileDownloader.fetch_all).parameters), {
            'self', 'attachment_refs', 'workspace',
        })


class FileDownloadValidationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.config = {
            'baseUrl': 'https://files.test', 'domainName': 'routing.test',
            'remoteUrl': 'https://public.test', 'downloadPath': '/file/{fileId}/download',
            'maxFileBytes': 1024 * 1024, 'timeoutSeconds': 600,
        }
        self.enterContext(patch('runtime.file_download.file_service_config', return_value=self.config))
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    async def fetch(self, handler, *, refs=None, **kwargs):
        def respond(request):
            self.assertEqual(request.method, 'GET')
            self.assertEqual(request.content, b'')
            self.assertNotIn('authorization', request.headers)
            return handler(request)
        return await FileDownloader(transport=httpx.MockTransport(respond), **kwargs).fetch_all(
            refs or [AttachmentRef('file_1')], workspace=self.root / 'input')

    async def test_missing_configuration_has_stable_failure_but_allows_empty_input(self):
        events = []
        with patch('runtime.file_download.file_service_config',
                   side_effect=FileServiceError('file_service_not_configured')):
            downloader = FileDownloader(event_sink=lambda kind, data: events.append((kind, data)))
        self.assertFalse(downloader.configured)
        self.assertEqual(await downloader.fetch_all([], workspace=self.root / 'input'), ())
        with self.assertRaises(FileDownloadUnavailableError) as caught:
            await downloader.fetch_all([AttachmentRef('file_1')], workspace=self.root / 'input')
        self.assertEqual(caught.exception.code, 'file_download_unavailable')
        self.assertEqual(events[-1][1]['errorCode'], 'file_download_unavailable')
        self.assertFalse((self.root / 'input').exists())

    def test_invalid_limits_are_rejected_instead_of_using_defaults(self):
        for field in ('max_bytes', 'timeout_ms'):
            for value in (0, -1, True, 1.5, '100'):
                with self.subTest(field=field, value=value), self.assertRaises(FileDownloadConfigurationError):
                    FileDownloader(**{field: value})

    async def test_response_names_and_mime_cannot_escape_file_boundary(self):
        for name in ('..%2Fsecret.docx', '..%5Csecret.docx', '.', 'CON', 'con.data.docx',
                     'LPT9.pdf', 'report%00.pdf', 'report%0A.pdf', '%FF.pdf', 'report.pdf.'):
            with self.subTest(name=name), self.assertRaises(FileDownloadValidationError):
                await self.fetch(lambda _: httpx.Response(200, content=b'data', headers={
                    'content-disposition': 'attachment; filename=' + name}))
            self.assertEqual(list((self.root / 'input').iterdir()), [])
        with self.assertRaises(FileDownloadValidationError):
            await self.fetch(lambda _: httpx.Response(200, content=b'data', headers={
                'content-disposition': 'attachment; filename=report.pdf', 'content-type': 'invalid'}))

    async def test_declared_size_must_be_valid_and_match_actual_content(self):
        for length in ('-1', 'invalid', '', '1000001', '3', '5'):
            with self.subTest(length=length), self.assertRaises(FileDownloadValidationError):
                await self.fetch(lambda _: httpx.Response(200, stream=httpx.ByteStream(b'data'), headers={
                    'content-disposition': 'attachment; filename=report.pdf', 'content-length': length}),
                    max_bytes=1000000)
            self.assertEqual(list((self.root / 'input').iterdir()), [])

    async def test_deployment_file_limit_is_always_enforced(self):
        self.config['maxFileBytes'] = 3
        with self.assertRaises(FileDownloadValidationError):
            await self.fetch(lambda _: httpx.Response(200, content=b'data', headers={
                'content-disposition': 'attachment; filename=report.pdf'}), max_bytes=100)
        self.assertEqual(list((self.root / 'input').iterdir()), [])

    async def test_duplicate_names_are_unique_ignoring_case(self):
        files = await self.fetch(lambda request: httpx.Response(200, content=b'data', headers={
            'content-disposition': 'attachment; filename=' + (
                'report.pdf' if 'file_1' in request.url.path else 'REPORT.pdf')}),
            refs=[AttachmentRef('file_1'), AttachmentRef('file_2'), AttachmentRef('file_2')])
        self.assertEqual(len({f.safe_name.lower() for f in files}), 3)
        self.assertTrue(all(f.path.read_bytes() == b'data' for f in files))

    async def test_http_timeout_returns_safe_error_and_cleans_previous_files(self):
        events = []
        def handler(request):
            if '/file_2/' in request.url.path:
                raise httpx.ReadTimeout('private upstream credentials and address')
            return httpx.Response(200, content=b'data', headers={
                'content-disposition': 'attachment; filename=report.pdf'})
        with self.assertRaises(FileDownloadTimeoutError) as caught:
            await self.fetch(handler, refs=[AttachmentRef('file_1'), AttachmentRef('file_2')],
                             event_sink=lambda kind, data: events.append((kind, data)))
        self.assertEqual(caught.exception.code, 'file_download_timeout')
        self.assertNotIn('private upstream', str(caught.exception) + json.dumps(events))
        self.assertEqual(list((self.root / 'input').iterdir()), [])

    async def test_http_client_uses_configured_download_timeout(self):
        settings = replace(RUNTIME_SETTINGS, timeouts=replace(
            RUNTIME_SETTINGS.timeouts, file_download_ms=1234))
        def handler(request):
            self.assertEqual(set(request.extensions['timeout'].values()), {1.234})
            return httpx.Response(200, content=b'data', headers={
                'content-disposition': 'attachment; filename=report.pdf'})
        with patch('runtime.file_download.RUNTIME_SETTINGS', settings):
            await self.fetch(handler)

    async def test_broken_observer_does_not_fail_a_valid_download(self):
        def observer(*_):
            raise RuntimeError('private observer detail')
        with self.assertLogs('ccsdk.file_download', level='WARNING') as logs:
            files = await self.fetch(lambda _: httpx.Response(200, content=b'data', headers={
                'content-disposition': 'attachment; filename=report.pdf'}), event_sink=observer)
        self.assertEqual(files[0].path.read_bytes(), b'data')
        self.assertNotIn('private observer detail', ''.join(logs.output))

    async def test_symlink_target_outside_workspace_is_rejected(self):
        outside = self.root / 'outside.pdf'
        outside.write_bytes(b'keep')
        workspace = self.root / 'input'
        workspace.mkdir()
        try:
            (workspace / 'report.pdf').symlink_to(outside)
        except OSError:
            self.skipTest('当前平台不允许创建符号链接')
        with self.assertRaises(FileDownloadValidationError):
            await self.fetch(lambda _: httpx.Response(200, content=b'data', headers={
                'content-disposition': 'attachment; filename=report.pdf'}))
        self.assertEqual(outside.read_bytes(), b'keep')
