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
    def test_loadtest_signs_for_explicit_test_identity_without_deployment_tenant(self):
        spec = importlib.util.spec_from_file_location(
            'deployment_loadtest', Path(__file__).resolve().parents[2] / 'deploy' / 'loadtest.py')
        loadtest = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(loadtest)
        from runtime.auth import verify_run_jwt
        config = {'security': {
            'runtimeJwtSecret': 'private-loadtest-key', 'runtimeJwtIssuer': 'configured-issuer',
            'runtimeJwtAudience': 'configured-audience'}}
        body = {'runId': 'loadtest-run', 'messageId': 'loadtest-message',
                'businessSessionId': 'loadtest-session', 'capabilityRef': 'conversation',
                'domainName': 'school.example.test'}
        headers = loadtest.authorization_headers(config, body, 'run.execute', tenant_id='customer-a')
        claims = verify_run_jwt(headers['Authorization'][7:], 'private-loadtest-key', body=body,
            tenant_id='customer-a', issuer='configured-issuer', audience='configured-audience')
        self.assertEqual(claims['tenant'], 'customer-a')
        self.assertNotIn('domainName', claims)

    def test_probe_accepts_actual_runtime_routes_and_terminal_event(self):
        spec = importlib.util.spec_from_file_location(
            'deployment_smoke', Path(__file__).resolve().parents[2] / 'deploy' / 'smoke.py')
        smoke = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(smoke)
        client_type = httpx.AsyncClient

        def client(**kwargs):
            return client_type(**kwargs, transport=httpx.ASGITransport(app=server.app))

        async def sdk_output(_, **kwargs):
            yield {'type': 'text', 'text': '391'}
            yield {'type': 'result', 'ok': True}

        async def exercise():
            with tempfile.TemporaryDirectory() as directory, RunStore(':memory:') as store:
                with patch.multiple(server, RUN_STORE=store, RUNTIME_JWT_SECRET='probe-secret',
                                    PROJECT_ROOT=Path(directory), DEFAULT_MODEL='test-model',
                                    internal_tasks={}, internal_subscribers={}):
                    with patch.object(server, 'stream_agent', sdk_output), \
                         patch.object(server, '_runtime_mode_for_request', return_value='query'), \
                         patch.object(smoke.httpx, 'AsyncClient', client), \
                         patch('runtime.deployment_config._DEPLOYMENT', {'security': {'runtimeJwtSecret':'probe-secret'}}):
                        await smoke.main(tenant='deployment-check', domain_name='school.example.test')
                        await asyncio.gather(*server.internal_tasks.values())

        asyncio.run(exercise())
