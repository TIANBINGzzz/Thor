import copy
import os
import unittest
from unittest.mock import patch

from runtime import mcp_auth


class MCPArgumentTests(unittest.TestCase):
    def test_binding_copies_and_isolates_registered_mcp_arguments(self):
        rules = {'first': {'required': True, 'transport': 'sdk',
                           'arguments': {'user_context_token': 'platformBearer'}},
                 'second': {'required': True, 'transport': 'sdk',
                            'arguments': {'identity': 'platformBearer'}}}
        with patch.dict(mcp_auth.MCP_AUTH_RULES, rules):
            a = mcp_auth.MCPArgumentBinding('first', {'platformBearer': 'one'})
            b = mcp_auth.MCPArgumentBinding('second', {'platformBearer': 'two'})
            source = {'payload': {'year': 2025}}
            before = copy.deepcopy(source)
            env = dict(os.environ)
            self.assertEqual(a.inject(source), {**source, 'user_context_token': 'one'})
            self.assertEqual(b.inject(source), {**source, 'identity': 'two'})
            self.assertEqual(source, before)
            self.assertEqual(dict(os.environ), env)
            with self.assertRaises(mcp_auth.MCPAuthError):
                a.inject({'user_context_token': 'override'})
            with self.assertRaises(mcp_auth.MCPAuthError):
                a.check_response({'error': 'one'})
            a.clear()
            with self.assertRaises(mcp_auth.MCPAuthError):
                a.inject(source)
            self.assertEqual(b.inject(source)['identity'], 'two')

    def test_unregistered_missing_or_invalid_mapping_fails(self):
        with self.assertRaises(mcp_auth.MCPAuthError):
            mcp_auth.MCPArgumentBinding('unknown', {'platformBearer': 'one'})
        with self.assertRaises(mcp_auth.MCPAuthError):
            mcp_auth.MCPArgumentBinding('campus', {})
        with patch.dict(mcp_auth.MCP_AUTH_RULES, {'invalid': {
                'required': True, 'transport': 'sdk', 'arguments': {'token': 'userInput'}}}):
            with self.assertRaises(mcp_auth.MCPAuthError):
                mcp_auth.MCPArgumentBinding('invalid', {'platformBearer': 'one'})

    def test_response_check_handles_json_escaped_credentials(self):
        token = 'synthetic\\credential"'
        binding = mcp_auth.MCPArgumentBinding('campus', {'platformBearer': token})
        with self.assertRaises(mcp_auth.MCPAuthError):
            binding.check_response({'nested': [token]})
