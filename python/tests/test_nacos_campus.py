import unittest
from unittest.mock import patch

from runtime.nacos_config import NacosConfigError, campus_mcp_config


class CampusConfigTests(unittest.TestCase):
    def test_only_validated_connection_fields_leave_config_center(self):
        connection = {'url': 'https://campus.test/mcp', 'domainName': 'campus.test'}
        with patch('runtime.nacos_config.fetch_config', return_value={
                'campusMcp': connection, 'fileService': {'private': 'value'}}):
            self.assertEqual(campus_mcp_config({}), connection)

    def test_missing_invalid_or_extra_fields_fail_closed(self):
        for config in (None, {}, {'url': 'http://user:secret@host/mcp', 'domainName': 'host'},
                       {'url': 'https://host/mcp?token=secret', 'domainName': 'host'},
                       {'url': 'https://host/mcp', 'domainName': 'host\r\nsecret'},
                       {'url': 'https://host/mcp', 'domainName': 'host', 'headers': {'Authorization': 'secret'}}):
            with self.subTest(config=config), patch('runtime.nacos_config.fetch_config',
                                                    return_value={'campusMcp': config}):
                with self.assertRaisesRegex(NacosConfigError, '^campus_mcp_config_invalid$'):
                    campus_mcp_config({})
