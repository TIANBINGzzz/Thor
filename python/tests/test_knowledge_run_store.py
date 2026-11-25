import json
import unittest

from runtime.run_store import RunStore


def record(ref='k1', chunk_id='chunk-1'):
    return {'ref':ref,'connection_ref':'school','library_ref':'policy-lib',
        'external_library_id':'external-kb','knowledge_id':'doc-1','chunk_id':chunk_id,
        'chunk_index':1,'snapshot':{'ref':ref,'libraryName':'政策库','documentTitle':'政策.pdf',
            'excerpt':'引用原文','excerptTruncated':False,'sources':[],'moreLocations':0}}


class KnowledgeRunStoreTests(unittest.TestCase):
    def setUp(self):
        self.store = RunStore(':memory:')
        self.store.create_run('knowledge-run', status='running', tenant_id='school', user_id='user')

    def tearDown(self):
        self.store.close()

    def test_source_snapshot_and_private_mapping_are_stored_separately_from_sse(self):
        self.store.save_knowledge_sources('knowledge-run', [record()])
        self.store.append_event('knowledge-run', {'type':'knowledge.sources',
            'payload':{'items':[record()['snapshot']]}})
        rows = self.store._connection.execute(
            'SELECT connection_ref,external_library_id,chunk_id,snapshot_json FROM run_knowledge_sources').fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['external_library_id'], 'external-kb')
        self.assertEqual(rows[0]['chunk_id'], 'chunk-1')
        self.assertEqual(json.loads(rows[0]['snapshot_json']), record()['snapshot'])
        event = self.store.events_after('knowledge-run')[0]
        self.assertNotIn('external-kb', json.dumps(event))
        self.assertNotIn('chunk-1', json.dumps(event))

    def test_cleanup_removes_terminal_events_and_sources_after_24_hours(self):
        self.store.update_status('knowledge-run','succeeded')
        self.store.save_knowledge_sources('knowledge-run', [record()])
        self.store.append_event('knowledge-run', {'type':'knowledge.sources',
            'payload':{'items':[record()['snapshot']]}})
        self.store.create_run('active-run', status='running', tenant_id='school', user_id='user')
        self.store.create_run('recent-run', status='failed', tenant_id='school', user_id='user')
        now = 3_000_000_000
        expired_at = now - 86_400_001
        self.store._connection.execute('UPDATE runs SET updated_at=? WHERE run_id=?',
                                       (expired_at,'knowledge-run'))
        self.store._connection.execute('UPDATE runs SET updated_at=? WHERE run_id=?',
                                       (now - 86_399_999,'recent-run'))
        self.store._connection.commit()

        removed = self.store.cleanup_expired(now_ms=now)

        self.assertEqual(removed, 1)
        self.assertEqual(self.store.events_after('knowledge-run'), [])
        self.assertEqual(self.store._connection.execute(
            'SELECT COUNT(*) FROM run_knowledge_sources WHERE run_id=?',('knowledge-run',)).fetchone()[0], 0)
        self.assertEqual(self.store.get_run('knowledge-run')['status'], 'succeeded')
        self.assertEqual(self.store.get_run('active-run')['status'], 'running')
        self.assertEqual(len(self.store.events_after('recent-run')), 0)
