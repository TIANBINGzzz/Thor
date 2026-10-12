import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from runtime.private_trace import sanitize
from runtime import private_trace
from runtime.run_store import RunStore

class PrivateTraceTests(unittest.TestCase):
    def test_timing_uses_local_monotonic_clock_and_keeps_first_occurrence(self):
        with patch.dict('os.environ', {'CCSDK_ENABLE_RUN_TRACE': '1'}), \
             patch.object(private_trace.time, 'perf_counter', side_effect=[10, 10.125, 11]), \
             patch.object(private_trace.time, 'process_time', side_effect=[2, 2.025, 2.05]):
            timing = private_trace.Timing('worker_run')
            timing.mark('first_text')
            timing.mark('first_text')
        event = timing.event()
        self.assertEqual(event['version'], 1)
        self.assertEqual(event['elapsedMs']['first_text'], 125)
        self.assertEqual(event['cpuMs']['first_text'], 25)

    def test_timing_is_off_by_default_and_rejects_arbitrary_fields(self):
        with patch.dict('os.environ', {}, clear=True):
            timing = private_trace.Timing('worker_run')
            timing.mark('first_text')
            self.assertIsNone(timing.event())
        raw = {'type': 'performance', 'version': 1, 'scope': 'worker_run',
               'elapsedMs': {'first_text': 12, 'prompt': 'private'},
               'cpuMs': {'first_text': float('nan')}, 'credentials': 'secret'}
        event = private_trace.performance_event(raw)
        self.assertEqual(event['elapsedMs'], {'first_text': 12})
        self.assertEqual(event['cpuMs'], {})
        self.assertNotIn('credentials', event)
        self.assertIsNone(private_trace.performance_event({**raw, 'scope': 'secret'}))

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

    def test_trace_persists_separately_and_cascades_with_run(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'runs.sqlite3'
            store=RunStore(path)
            store.create_run('run-1',tenant_id='t',user_id='u')
            store.append_trace('run-1',{'type':'tool_use','id':'call-1','name':'Read'})
            store.append_trace('run-1',{'type':'tool_result','id':'call-1','text':'hello'})
            self.assertEqual(store.events_after('run-1'),[])
            store.close()
            store=RunStore(path)
            try:
                self.assertEqual(store.traces_after('run-1',1)[0]['event']['text'],'hello')
                store.delete_run('run-1')
                self.assertEqual(store.traces_after('run-1'),[])
            finally:store.close()
