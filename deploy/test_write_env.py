import importlib.util
import os
from pathlib import Path
import tempfile
import unittest

from dotenv import dotenv_values
from io import StringIO

spec = importlib.util.spec_from_file_location("write_env", Path(__file__).with_name("write-env.py"))
writer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(writer)


class DeploymentEnvironmentTests(unittest.TestCase):
    def environment(self):
        return {"ANTHROPIC_AUTH_TOKEN": "test '$() ` = # \\ token",
                "ANTHROPIC_BASE_URL": "https://example.com", "ANTHROPIC_MODEL": "test",
                "CCSDK_RUNTIME_JWT_SECRET": "s" * 48, "UNRELATED_SECRET": "excluded"}

    def test_raw_runtime_round_trip_and_allowlist(self):
        environment = self.environment()
        parsed = dict(line.split("=", 1) for line in writer.render(environment).splitlines())
        self.assertEqual(parsed["ANTHROPIC_AUTH_TOKEN"], environment["ANTHROPIC_AUTH_TOKEN"])
        self.assertNotIn("UNRELATED_SECRET", parsed)

    def test_workflow_dotenv_special_characters(self):
        environment = {"DB_HOST": "db.internal", "DB_USER": "readonly", "DB_PASSWORD": " '$test # \\ ` = "}
        self.assertEqual(dict(dotenv_values(stream=StringIO(writer.render(environment, database=True)))), environment)

    def test_rejects_missing_multiline_and_interpolation_without_values(self):
        for value in ("", "sensitive\nINJECTED=yes", "sensitive\rvalue", "sensitive\x00value"):
            environment = self.environment()
            environment["ANTHROPIC_AUTH_TOKEN"] = value
            with self.assertRaises(ValueError) as raised:
                writer.render(environment)
            self.assertNotIn("sensitive", str(raised.exception))
        with self.assertRaises(ValueError):
            writer.render({"DB_HOST": "db", "DB_USER": "u", "DB_PASSWORD": "${PASSWORD}"}, database=True)

    @unittest.skipUnless(os.name == "posix", "POSIX deployment file permissions")
    def test_atomic_rotation_preserves_restricted_permissions(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "runtime.env"
            writer.atomic_write(path, "old")
            writer.atomic_write(path, "new")
            self.assertEqual(path.read_text(), "new")
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(list(Path(directory).iterdir()), [path])


if __name__ == "__main__":
    unittest.main()
