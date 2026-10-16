import json
import tempfile
import unittest
import os
from unittest.mock import patch
from pathlib import Path
from runtime.observability import ObservationStore, Observer, trace_id, create_observer

class ObservationTests(unittest.TestCase):
    def test_broken_observation_config_does_not_prevent_runtime_startup(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            (root/'config').mkdir()
            for value in ('[broken', 'queue-size: 0', '- invalid'):
                (root/'config'/'observability.yml').write_text(value,encoding='utf-8')
                observer=create_observer(root)
                self.assertFalse(observer.enabled)
                observer.close()

    def test_cursor_survives_restart_and_reports_expired_range(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/"observe.db"
            store=ObservationStore(path, max_records=3, retention_seconds=3600)
            for n in range(5): store.append({"kind":"milestone","runId":"r", "n":n})
            page=store.read(0, 2)
            self.assertTrue(page["gap"])
            self.assertEqual([r["sequence"] for r in page["records"]], [3,4])
            store.close()
            store=ObservationStore(path, max_records=3, retention_seconds=3600)
            self.assertEqual(store.read(4,10)["records"][0]["n"],4)
            store.close()

    def test_observer_collects_all_capabilities_and_redacts_credentials(self):
        with tempfile.TemporaryDirectory() as d:
            observer=Observer(Path(d)/"o.db", enabled=True, max_records=100)
            observer.emit("evidence", "r", {"text":"private body", "token":"business-secret"})
            observer.emit("evidence", "other-run", {"text":"second capability"})
            observer.emit("milestone", "r", {"name":"first_text", "authorization":"Bearer abcdefgh"})
            observer.flush()
            records=observer.read(0,100)["records"]
            observer.close()
            self.assertEqual(len(records),3)
            self.assertEqual(records[0]['data']['text'], 'private body')
            self.assertNotIn("abcdefgh",json.dumps(records))
            self.assertNotIn("business-secret",json.dumps(records))

    @patch.dict(os.environ, {'CCSDK_OBSERVABILITY_ENABLED': '1'})
    def test_instance_identity_is_discovered_and_persists_with_storage(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root/'config').mkdir()
            (root/'config/observability.yml').write_text('enabled: true', encoding='utf-8')
            first = create_observer(root)
            identity = first.instance_id
            first.close()
            second = create_observer(root)
            second_identity = second.instance_id
            second.close()
            self.assertEqual(second_identity, identity)
            other = root/'other'
            (other/'config').mkdir(parents=True)
            (other/'config/observability.yml').write_text('enabled: true', encoding='utf-8')
            third = create_observer(other)
            third_identity = third.instance_id
            third.close()
            self.assertNotEqual(third_identity, identity)

    def test_browser_replay_cannot_replace_first_body_and_missing_is_not_zero(self):
        with tempfile.TemporaryDirectory() as d:
            observer=Observer(Path(d)/"o.db", enabled=True, max_records=100)
            self.assertFalse(observer.browser("r", {"name":"first_body", "elapsedMs":12,"nonempty":False}))
            self.assertFalse(observer.browser("r", {"name":"first_body", "elapsedMs":20,"nonempty":True,"replay":True}))
            self.assertTrue(observer.browser("r", {"name":"first_body", "elapsedMs":120,"nonempty":True}))
            self.assertFalse(observer.browser("r", {"name":"first_body", "elapsedMs":999,"nonempty":True}))
            observer.flush()
            self.assertEqual(observer.read(0,100)["records"][0]["data"]["elapsedMs"],120)
            observer.close()

    def test_trace_identity_is_instance_scoped_and_stable(self):
        self.assertEqual(trace_id("a","r"), trace_id("a","r"))
        self.assertNotEqual(trace_id("a","r"), trace_id("b","r"))

    def test_span_identity_is_globally_unique_and_parent_links_resolve(self):
        with tempfile.TemporaryDirectory() as d:
            observer=Observer(Path(d)/'o.db',enabled=True)
            observer.span('first','run',1000,10)
            observer.span('second','run',1000,10)
            observer.performance('first',{'scope':'runtime','originUnixMs':1000,'elapsedMs':{'accepted':2}})
            observer.flush()
            spans=[r['data'] for r in observer.read(0,100)['records'] if r['kind']=='span']
            observer.close()
            self.assertNotEqual(spans[0]['spanId'],spans[1]['spanId'])
            self.assertEqual(spans[2]['parentSpanId'],spans[0]['spanId'])

    def test_bad_span_measurement_cannot_interrupt_business_caller(self):
        with tempfile.TemporaryDirectory() as d:
            observer=Observer(Path(d)/'o.db',enabled=True)
            try:
                observer.span('run','stage',None,10)
            finally:
                observer.close()
            self.assertEqual(observer.dropped,1)

    def test_sdk_usage_keeps_numeric_counts_without_treating_them_as_credentials(self):
        with tempfile.TemporaryDirectory() as d:
            observer=Observer(Path(d)/'o.db',enabled=True)
            observer.sdk('r',{'type':'result','inputTokens':12,'outputTokens':7,'costUsd':.01})
            observer.flush()
            data=observer.read(0,100)['records'][0]['data']
            observer.close()
            self.assertEqual(data['usage'],{'input':12,'output':7})
            self.assertEqual(data['costUsd'],.01)

    def test_browser_first_is_deduplicated_after_restart(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/"o.db"
            for expected in (True,False):
                observer=Observer(path,enabled=True)
                self.assertEqual(observer.browser("r",{"name":"first_body","elapsedMs":50,"nonempty":True}),expected)
                observer.close()

    def test_performance_keeps_wall_anchor_without_cross_clock_subtraction(self):
        from runtime.private_trace import performance_event
        event=performance_event({"type":"performance","version":1,"scope":"worker_run", "originUnixMs":1000,"clockId":"worker-a", "elapsedMs":{"query_sent":25}})
        self.assertEqual(event.get("originUnixMs"),1000)
        self.assertEqual(event.get("clockId"),"worker-a")
