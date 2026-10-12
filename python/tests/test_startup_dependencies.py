"""无数据库的会话不应付出数据库执行器的导入成本。"""
from pathlib import Path
import subprocess
import sys
import unittest


class StartupDependenciesTests(unittest.TestCase):
    def test_conversation_options_do_not_load_database_engine_or_sql_parser(self):
        # 独立解释器避免测试收集已经导入数据库模块而掩盖启动回归。
        program = '''
import sys
import agent_worker
from runtime.config import build_options, create_run_services
payload = {'capability_ref': 'conversation'}
assert create_run_services(payload) is None
options = build_options(payload)
assert 'data' not in options.mcp_servers
loaded = [name for name in ('sqlalchemy', 'sqlglot', 'data_access.executor') if name in sys.modules]
assert not loaded, 'Unneeded database startup imports: ' + ', '.join(loaded)
'''
        result = subprocess.run(
            [sys.executable, '-c', program],
            cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
