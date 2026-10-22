"""新增 MCP 只登记可信资产，不修改 Provider、鉴权或显示字典。"""

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from runtime.deployment_config import ConfigSnapshot
from runtime.tool_catalog import ToolCatalog
from runtime.mcp_auth import inject_mcp_authentication, MCPAuthError


class MCPProviderTests(unittest.TestCase):
    def catalog(self, root, transport='http'):
        directory = Path(root) / 'new-system'
        directory.mkdir()
        value = {'ref': directory.name, 'version': 1, 'implementation': transport + '-mcp',
                 'transport': transport, 'lifecycle': 'per_run', 'category': 'integration',
                 'description': '新系统', 'scope': 'namespace', 'operations': [],
                 'connection': {'url': '${system.url}'} if transport == 'http' else
                               {'command': 'system-mcp', 'args': ['serve']},
                 'auth': {'required': True, 'header': 'Authorization', 'prefix': 'Bearer '}
                         if transport == 'http' else {'required': True, 'env': 'SYSTEM_TOKEN'},
                 'displayKeys': {'find': 'data.query'}}
        (directory / 'tool.json').write_text(json.dumps(value), encoding='utf-8')
        return ToolCatalog(root)

    def test_new_http_mcp_uses_catalog_connection_auth_and_display(self):
        from runtime.mcp_providers import load_mcp_connections
        from runtime.tool_registry import build_registered_tools
        from runtime.event_display import ToolCallDisplays
        with tempfile.TemporaryDirectory() as root:
            catalog = self.catalog(root)
            before = dict(os.environ)
            with patch('runtime.tool_catalog.TOOL_CATALOG', catalog), \
                 patch('runtime.tool_registry.TOOL_CATALOG', catalog):
                entry = {'tools': ['new-system']}
                settings = ConfigSnapshot(values={'system.url': 'https://system.test/mcp'})
                connections = load_mcp_connections(entry, settings, catalog=catalog)
                registered = build_registered_tools(entry, {'mcp_connections': connections})
                with self.assertRaises(MCPAuthError):
                    inject_mcp_authentication(registered.servers, {})
                result = inject_mcp_authentication(registered.servers, {'platformBearer': 'one'})
                self.assertEqual(result['new-system']['headers'], {'Authorization': 'Bearer one'})
                self.assertNotIn('headers', registered.servers['new-system'])
                self.assertEqual(ToolCallDisplays().resolve('run', {'type': 'tool_use',
                    'name': 'mcp__new-system__find'})['toolKey'], 'data.query')
            self.assertEqual(dict(os.environ), before)

    def test_stdio_token_is_only_in_target_process_copy(self):
        from runtime.mcp_providers import load_mcp_connections
        with tempfile.TemporaryDirectory() as root:
            catalog = self.catalog(root, 'stdio')
            connections = load_mcp_connections({'tools': ['new-system']}, ConfigSnapshot(values={}), catalog=catalog)
            with patch('runtime.tool_catalog.TOOL_CATALOG', catalog):
                servers = inject_mcp_authentication(connections, {'platformBearer': 'one'})
            self.assertEqual(servers['new-system']['env'], {'SYSTEM_TOKEN': 'one'})
            self.assertNotIn('env', connections['new-system'])
            self.assertNotIn('SYSTEM_TOKEN', os.environ)

    def test_http_credentials_in_url_rejected(self):
        from runtime.mcp_providers import load_mcp_connections
        with tempfile.TemporaryDirectory() as root:
            catalog = self.catalog(root)
            with self.assertRaises(ValueError):
                load_mcp_connections({'tools': ['new-system']},
                    ConfigSnapshot(values={'system.url': 'https://user:secret@system.test/mcp'}), catalog=catalog)

    def test_invalid_auth_target_or_provider_contract_rejected(self):
        for change in ({'auth': {'required': True, 'header': '', 'prefix': 'Bearer '}},
                       {'transport': 'sdk'}, {'lifecycle': 'per_client'}):
            with tempfile.TemporaryDirectory() as root:
                catalog = self.catalog(root)
                path = Path(root) / 'new-system/tool.json'
                value = json.loads(path.read_text(encoding='utf-8'))
                value.update(change)
                path.write_text(json.dumps(value), encoding='utf-8')
                with self.subTest(change=change), self.assertRaises(RuntimeError):
                    catalog.resolve('new-system')
