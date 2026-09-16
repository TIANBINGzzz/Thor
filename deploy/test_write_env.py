import base64
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from contextlib import redirect_stderr

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

    def test_custom_jwt_secret_survives_bundle_and_container_check(self):
        entrypoint = Path(__file__).with_name("entrypoint.py")
        for secret in ("short", "your_custom_key", "replace-with-is-allowed", "test-jwt-" * 8):
            with self.subTest(secret=secret):
                environment = {key: value for key, value in self.environment().items()
                               if key in writer.RUNTIME_KEYS}
                environment["CCSDK_RUNTIME_JWT_SECRET"] = secret
                encoded = base64.b64encode(json.dumps(environment).encode()).decode()
                decoded = writer.load_environment({"CCSDK_DEPLOY_ENV_B64": encoded})
                raw = dict(line.split("=", 1) for line in writer.render(decoded).splitlines())
                self.assertEqual(raw["CCSDK_RUNTIME_JWT_SECRET"], secret)
                checked = subprocess.run([sys.executable, str(entrypoint), "--check"],
                                         env={**os.environ, **raw}, capture_output=True, text=True)
                self.assertEqual(checked.returncode, 0, checked.stderr)
                self.assertIn("Deployment environment check passed", checked.stdout)
                self.assertNotIn(secret, checked.stdout + checked.stderr)

    def test_missing_or_blank_jwt_still_fails_bundle_and_container_check(self):
        entrypoint = Path(__file__).with_name("entrypoint.py")
        for secret in (None, "", "   "):
            with self.subTest(secret=secret):
                environment = self.environment()
                environment.pop("CCSDK_RUNTIME_JWT_SECRET")
                if secret is not None:
                    environment["CCSDK_RUNTIME_JWT_SECRET"] = secret
                with self.assertRaisesRegex(ValueError, "Missing deployment variable: CCSDK_RUNTIME_JWT_SECRET"):
                    writer.render(environment)
                process_env = dict(os.environ)
                process_env.pop("CCSDK_RUNTIME_JWT_SECRET", None)
                process_env.update(environment)
                checked = subprocess.run([sys.executable, str(entrypoint), "--check"],
                                         env=process_env, capture_output=True, text=True)
                self.assertNotEqual(checked.returncode, 0)
                self.assertEqual(checked.stderr.strip(),
                                 "Missing or invalid deployment settings: CCSDK_RUNTIME_JWT_SECRET")

    def test_protected_database_json_contains_credentials(self):
        import json
        config={'version':1,'sources':{name:{'connection':{'driver':'mysql+pymysql','host':name,
                'database':'test','username':'readonly','password':" '$test # \\ ` = ",
                'tls':{'mode':'disabled'}},'policy':{'users':[]}} for name in ('first','second')}}
        environment={'CCSDK_DATABASES_JSON':json.dumps(config)}
        rendered=json.loads(writer.render(environment,database=True))
        self.assertEqual(rendered,config)
        config['sources']['first']['connection']['tls']={'ca_file':'certificates/first.pem','verify_identity':True}
        environment['CCSDK_DATABASES_JSON']=json.dumps(config)
        with self.assertRaises(ValueError): writer.render(environment,database=True)
        environment['CCSDK_DATABASE_CERTIFICATES_JSON']=json.dumps({'first.pem':'certificate\ncontent'})
        self.assertEqual(json.loads(writer.render(environment,database=True)),config)
        environment['CCSDK_DATABASE_CERTIFICATES_JSON']=json.dumps({'../escape.pem':'certificate'})
        with self.assertRaises(ValueError): writer.render(environment,database=True)

    def test_rejects_missing_multiline_and_interpolation_without_values(self):
        for value in ("", "sensitive\nINJECTED=yes", "sensitive\rvalue", "sensitive\x00value"):
            environment = self.environment()
            environment["ANTHROPIC_AUTH_TOKEN"] = value
            with self.assertRaises(ValueError) as raised:
                writer.render(environment)
            self.assertNotIn("sensitive", str(raised.exception))
        with self.assertRaises(ValueError):
            writer.render({'CCSDK_DATABASES_JSON':'{}'}, database=True)

    def test_missing_directory_fails_before_reading_secrets(self):
        with mock.patch.dict(os.environ, {}, clear=True), mock.patch.object(sys, "argv", ["write-env.py"]):
            with mock.patch.object(writer, "render") as render, redirect_stderr(StringIO()) as stderr:
                with self.assertRaises(SystemExit) as raised:
                    writer.main()
                self.assertEqual(raised.exception.code, 2)
                render.assert_not_called()
                self.assertIn("--directory or CCSDK_CONFIG_DIRECTORY", stderr.getvalue())

    @unittest.skipUnless(os.name == "posix", "POSIX deployment file permissions")
    def test_database_generation_permissions_and_multiple_sources(self):
        import json
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            config={'version':1,'sources':{name:{'connection':{'driver':'mysql+pymysql','host':name,
                    'database':'test','username':'reader','password':'test-secret','tls':{'mode':'disabled'}},
                    'policy':{'users':[]}} for name in ('first','second')}}
            environment={**self.environment(),'CCSDK_DATABASES_JSON':json.dumps(config)}
            chown=mock.patch.object(writer.os,'chown') if os.geteuid()!=0 else mock.patch.object(writer.os,'chown',wraps=os.chown)
            with mock.patch.dict(os.environ,environment,clear=True), chown, mock.patch.object(writer.os,'geteuid',return_value=0), \
                 mock.patch.object(sys,'argv',['write-env.py','--directory',str(root),'--database']):
                writer.main()
            self.assertEqual(json.loads((root/'databases.json').read_text()),config)
            self.assertEqual((root/'databases.json').stat().st_mode & 0o777,0o400)
            self.assertEqual(root.stat().st_mode & 0o777,0o750)
            self.assertEqual((root/'runtime.env').stat().st_mode & 0o777,0o600)
            self.assertFalse((root/'data').exists())

    @unittest.skipUnless(os.name == "posix", "POSIX deployment file permissions")
    def test_configured_directory_and_cli_override(self):
        script = Path(__file__).with_name("write-env.py").resolve()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            environment = {**os.environ, **self.environment(), "CCSDK_CONFIG_DIRECTORY": "from env"}
            for arguments, destination in (([], "from env"), (["--directory", "from argument"], "from argument")):
                result = subprocess.run([sys.executable, str(script), *arguments], cwd=root,
                                        env=environment, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                output = root / destination / "runtime.env"
                self.assertEqual(output.read_text(), writer.render(environment))
                self.assertEqual(output.stat().st_mode & 0o777, 0o600)
                self.assertEqual(output.parent.stat().st_mode & 0o777, 0o700)

    @unittest.skipUnless(os.name == "posix" and shutil.which("flock"), "Linux deployment shell and lock")
    def test_deploy_uses_configured_paths_and_shared_lock(self):
        import fcntl

        script = Path(__file__).with_name("deploy.sh").resolve()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            binary = root / "bin"
            binary.mkdir()
            docker = binary / "docker"
            docker.write_text('#!/bin/sh\nif [ "$1" = version ]; then echo linux/amd64; exit 0; fi\nif [ "$1" = image ]; then exit 0; fi\nif [ "$1" = compose ] && [ "$2" = version ]; then echo 2.30.1; exit 0; fi\nprintf "%s|%s|%s\\n" "$CCSDK_ENV_FILE" "$CCSDK_CONFIG_DIRECTORY" "$*" >> "$TEST_DOCKER_LOG"\n')
            docker.chmod(0o700)
            config = root / "config with spaces"
            log = root / "docker.log"
            environment = {**os.environ, "PATH": str(binary) + os.pathsep + os.environ["PATH"],
                           "CCSDK_IMAGE": "test:paths", "CCSDK_GENERATE_ENV": "0",
                           "CCSDK_WITH_DATABASE": "1", "CCSDK_PULL_IMAGE": "0",
                           "CCSDK_CONFIG_DIRECTORY": os.path.relpath(config, script.parent), "TEST_DOCKER_LOG": str(log)}
            for key in ("CCSDK_ENV_FILE", "CCSDK_DEPLOY_LOCK_FILE"):
                environment.pop(key, None)
            result = subprocess.run(["sh", str(script)], cwd=root, env=environment, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            calls = log.read_text().splitlines()
            self.assertTrue(all(line.startswith(f"{config}/runtime.env|{config}|") for line in calls))
            self.assertIn("-f compose.database.yaml config --quiet", calls[0])
            self.assertIn("up -d --force-recreate --wait", calls[-1])
            with (config / "deploy.lock").open("w") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                blocked = subprocess.run(["sh", str(script)], env=environment, capture_output=True, text=True)
                self.assertNotEqual(blocked.returncode, 0)
                self.assertIn("Another deployment", blocked.stderr)
                self.assertEqual(log.read_text().splitlines(), calls)
            environment.pop("CCSDK_CONFIG_DIRECTORY")
            missing = subprocess.run(["sh", str(script)], env=environment, capture_output=True, text=True)
            self.assertNotEqual(missing.returncode, 0)
            self.assertEqual(log.read_text().splitlines(), calls)

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
