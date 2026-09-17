"""Check packaged database JSON without contacting a database or printing secrets."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class DatabaseConfigTests(unittest.TestCase):
    def check(self, content):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "databases.json"
            if content is not None:
                path.write_text(content, encoding="utf-8")
            env = {**os.environ, "CCSDK_DATABASES_FILE": str(path),
                   "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "python")}
            return subprocess.run([sys.executable, "-m", "data_access", "check-config"],
                                  env=env, capture_output=True, text=True, timeout=15)

    def test_valid_config_is_checked_offline_without_revealing_credentials(self):
        config = {"version": 1, "sources": {"example": {
            "connection": {"host": "unreachable.invalid", "password": "private-db-password"},
            "policy": {"revision": "1"}}}}
        result = self.check(json.dumps(config))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {"status": "ok", "sources_checked": 1})
        self.assertNotIn("private-db-password", result.stdout + result.stderr)

    def test_missing_malformed_or_empty_config_fails_without_echoing_values(self):
        for content in (None, '{"password":"private-db-password",',
                        '{"version":1,"sources":{}}',
                        '{"version":1,"sources":{"example":{"connection":{},"policy":{}}}}'):
            with self.subTest(content=content):
                result = self.check(content)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(json.loads(result.stdout), {"status": "failed", "code": "CONFIG_INVALID"})
                self.assertNotIn("private-db-password", result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
