"""真实快照/存储/Runtime链路，仅替换SDK与外部HTTP服务。"""

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
import server
from runtime.artifact_delivery import ArtifactDelivery
from runtime.protocol import AgentRunRequest
from runtime.run_store import RunStore
from runtime.session_actor import SessionActor
from tests.test_session_actor import FakeClientWorker
from tools.artifacts import publish_artifact


class ArtifactRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_run_terminal_waits_for_upload_and_replay_matches_state(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = RunStore(root / 'runs.sqlite3')
            config = root / 'files.json'
            config.write_text(json.dumps({'fileService': {'baseUrl': 'https://files.test',
                'remoteUrl': 'https://files.test', 'domainName': 'files.test'}}))
            sending, release = asyncio.Event(), asyncio.Event()
            async def upload(request):
                sending.set()
                await release.wait()
                return httpx.Response(200, json={'state': 200, 'success': True, 'data': {
                    'id': 'file_01', 'fileName': 'result.txt', 'fileSize': 5,
                    'fileSuffix': 'txt', 'url': 'private/path'}})
            delivery = ArtifactDelivery(store, root / 'archive', server._notify_stored_event,
                env={'CCSDK_DATABASES_FILE': str(config)}, transport=httpx.MockTransport(upload))
            request = AgentRunRequest.from_dict({'protocol': 'agent-run/v1', 'runId': 'run_01',
                'messageId': 'msg_01', 'businessSessionId': 'session_01', 'input': {'text': 'write'}})
            store.create_run('run_01', request=request, tenant_id='tenant', user_id='user')
            async def stream(payload):
                work = Path(payload['work_directory'])
                work.mkdir(parents=True, exist_ok=True)
                (work / 'result.txt').write_bytes(b'hello')
                item = publish_artifact('result.txt', 'result.txt', work,
                    payload['deliverables_directory'], payload['session_directory'])
                yield {'type': 'artifact.published', 'artifactId': item['artifactId']}
                yield {'type': 'result', 'ok': True}
            with patch.multiple(server, RUN_STORE=store, PROJECT_ROOT=root, ARTIFACT_DELIVERY=delivery,
                                internal_tasks={}, internal_subscribers={}, pending_terminals={}, MODELS=['test']), \
                 patch.object(server, '_runtime_mode_for_request', return_value='query'), \
                 patch.object(server, 'stream_agent', stream):
                task = asyncio.create_task(server._execute_internal_run(request, {'tenant': 'tenant', 'sub': 'user'}))
                try:
                    await asyncio.wait_for(sending.wait(), 3)
                    self.assertEqual(store.get_run('run_01')['status'], 'running')
                    self.assertNotIn('run.completed', [e['type'] for e in store.events_after('run_01')])
                    release.set()
                    await asyncio.wait_for(task, 3)
                    events = store.events_after('run_01')
                    types = [e['type'] for e in events]
                    self.assertEqual(types[-2:], ['artifact.ready', 'run.completed'])
                    self.assertIn({'name': 'saving_files', 'displayName': '正在保存文件'},
                                  [e['payload'] for e in events if e['type'] == 'phase'])
                    self.assertEqual(store.get_run('run_01')['status'], 'succeeded')
                    self.assertEqual(delivery.list('run_01')[0],
                                     {k: v for k, v in events[-2]['payload'].items() if k != 'displayName'})
                    self.assertEqual(delivery.list('run_02'), [])
                finally:
                    release.set()
                    await delivery.close()
                    await asyncio.gather(task, return_exceptions=True)
                    store.close()

    async def test_persistent_client_binds_publication_to_active_run(self):
        received = []
        async def notify(run_id, event):
            if event['type'] == 'artifact.published':
                received.append((run_id, event['artifactId']))
        def script(message):
            return [{'type': 'artifact.published', 'artifactId': message['run_id'] + '_file'},
                    {'type': 'client_run_completed', 'run_id': message['run_id']}]
        actor = SessionActor('session', {}, on_public_event=notify,
            worker_factory=lambda **kw: FakeClientWorker([script, script], worker_id=0))
        try:
            await actor.submit('run_01', {'prompt': 'one'})
            await actor.submit('run_02', {'prompt': 'two'})
            self.assertEqual(received, [('run_01', 'run_01_file'), ('run_02', 'run_02_file')])
        finally:
            await actor.close()
