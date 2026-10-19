import json
import asyncio
import unittest
from unittest.mock import patch
from runtime.telemetry import sanitize
from runtime import telemetry

class TelemetryTests(unittest.TestCase):
    def test_large_exception_fits_worker_jsonl_and_keeps_following_terminal(self):
        try:
            try:
                raise ValueError('中文错误' * 20000)
            except ValueError as error:
                raise RuntimeError('outer failure ' * 10000) from error
        except RuntimeError as error:
            event = telemetry.exception_event(error, scope='worker')
        async def receive():
            stream = asyncio.StreamReader()
            stream.feed_data((json.dumps(event, ensure_ascii=False) + '\n{"type":"worker_done"}\n').encode('utf-8'))
            stream.feed_eof()
            return json.loads(await stream.readline()), json.loads(await stream.readline())
        diagnostic, terminal = asyncio.run(receive())
        self.assertTrue(diagnostic['truncated'])
        self.assertEqual(terminal['type'], 'worker_done')

    def test_wrapped_sdk_exception_preserves_redacted_root_cause(self):
        try:
            try:
                raise ValueError('upstream transport rejected business-secret')
            except ValueError as error:
                raise RuntimeError('SDK request failed') from error
        except RuntimeError as error:
            event = telemetry.exception_event(error, scope='worker', secrets=('business-secret',))
        self.assertEqual(event['exceptionType'], 'RuntimeError')
        self.assertEqual(event['causes'][0]['exceptionType'], 'ValueError')
        self.assertIn('upstream transport rejected', event['causes'][0]['message'])
        self.assertNotIn('business-secret', json.dumps(event))
        self.assertTrue(event['causes'][0]['frames'])
        self.assertNotIn('locals', json.dumps(event))

    def test_timing_uses_local_monotonic_clock_and_keeps_first_occurrence(self):
        with patch.dict('os.environ', {'CCSDK_ENABLE_TIMING': '1'}), \
             patch.object(telemetry.time, 'perf_counter', side_effect=[10, 10.125, 11]), \
             patch.object(telemetry.time, 'process_time', side_effect=[2, 2.025, 2.05]):
            timing = telemetry.Timing('worker_run')
            timing.mark('first_text')
            timing.mark('first_text')
        event = timing.event()
        self.assertEqual(event['version'], 1)
        self.assertEqual(event['elapsedMs']['first_text'], 125)
        self.assertEqual(event['cpuMs']['first_text'], 25)

    def test_timing_is_off_by_default_and_rejects_arbitrary_fields(self):
        with patch.dict('os.environ', {}, clear=True):
            timing = telemetry.Timing('worker_run')
            timing.mark('first_text')
            self.assertIsNone(timing.event())
        raw = {'type': 'performance', 'version': 1, 'scope': 'worker_run',
               'elapsedMs': {'first_text': 12, 'prompt': 'private'},
               'cpuMs': {'first_text': float('nan')}, 'credentials': 'secret'}
        event = telemetry.performance_event(raw)
        self.assertEqual(event['elapsedMs'], {'first_text': 12})
        self.assertEqual(event['cpuMs'], {})
        self.assertNotIn('credentials', event)
        self.assertIsNone(telemetry.performance_event({**raw, 'scope': 'secret'}))

    def test_redacts_known_credentials_nested_headers_and_binary(self):
        with patch.dict('os.environ', {'IMAGE_API_KEY':'secret-image-key'}, clear=True):
            value = sanitize({'headers':{'Authorization':'secret-image-key'},
                'text':'secret-image-key business-secret Bearer abcdefgh data:image/png;base64,AA==',
                'input':{'path':'template.docx'}}, ['business-secret'])
        text = json.dumps(value)
        self.assertNotIn('secret-image-key',text)
        self.assertNotIn('business-secret',text)
        self.assertNotIn('abcdefgh',text)
        self.assertNotIn('AA==',text)
        self.assertEqual(value['input']['path'],'template.docx')
