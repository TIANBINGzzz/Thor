"""Run the deployment probe against the actual HTTP contract, with only SDK output substituted."""

import asyncio
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import httpx
import server
from runtime.run_store import RunStore


class DeploymentSmokeTests(unittest.TestCase):
    def test_probe_accepts_actual_runtime_routes_and_terminal_event(self):
        spec = importlib.util.spec_from_file_location(
            'deployment_smoke', Path(__file__).resolve().parents[2] / 'deploy' / 'smoke.py')
        smoke = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(smoke)
        client_type = httpx.AsyncClient

        def client(**kwargs):
            return client_type(**kwargs, transport=httpx.ASGITransport(app=server.app))

        async def sdk_output(_):
            yield {'type': 'text', 'text': '391'}
            yield {'type': 'result', 'ok': True}

        async def exercise():
            with tempfile.TemporaryDirectory() as directory, RunStore(':memory:') as store:
                with patch.multiple(server, RUN_STORE=store, RUNTIME_JWT_SECRET='probe-secret',
                                    PROJECT_ROOT=Path(directory), MODELS=['test-model'],
                                    internal_tasks={}, internal_subscribers={}):
                    with patch.object(server, 'stream_agent', sdk_output), \
                         patch.object(server, '_runtime_mode_for_request', return_value='query'), \
                         patch.object(smoke.httpx, 'AsyncClient', client), \
                         patch.dict(os.environ, {'CCSDK_RUNTIME_JWT_SECRET': 'probe-secret'}):
                        await smoke.main()
                        await asyncio.gather(*server.internal_tasks.values())

        asyncio.run(exercise())
