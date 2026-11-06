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
        return {'CCSDK_NACOS_URL':'https://nacos.example.test', 'CCSDK_NACOS_USERNAME':'reader',
                'CCSDK_NACOS_PASSWORD':"private '$() ` = # \\ token"}

    def test_bootstrap_round_trip_without_customer_secrets(self):
        environment = {**self.environment(), 'ANTHROPIC_AUTH_TOKEN':'model-secret',
            'CCSDK_RUNTIME_JWT_SECRET':'runtime-secret','CCSDK_IMAGE_API_KEY':'image-secret',
            'CCSDK_DATABASES_JSON':'private-db'}
        parsed = dict(line.split('=',1) for line in writer.render(environment).splitlines())
        self.assertEqual(parsed, self.environment())
        for key in set(environment)-set(self.environment()):
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, 'allowed variable'):
                writer.parse_bundle(json.dumps({**self.environment(),key:environment[key]}))

    def test_encoded_bundle_and_invalid_payloads(self):
        environment=self.environment()
        encoded=base64.b64encode(json.dumps(environment).encode()).decode()
        self.assertEqual(writer.load_environment({'CCSDK_DEPLOY_ENV_B64':encoded}),environment)
        for content in ('bad', '[]', '{"unknown":"secret"}'):
            with self.subTest(content=content), self.assertRaises(ValueError): writer.parse_bundle(content)
        for value in ('%%%', 'abc'):
            with self.assertRaises(ValueError): writer.load_environment({'CCSDK_DEPLOY_ENV_B64':value})

    def test_invalid_bootstrap_and_multiline_fail_without_values(self):
        for changes in ({'CCSDK_NACOS_URL':''},{'CCSDK_NACOS_PASSWORD':''},
                        {'CCSDK_NACOS_URL':'https://user:private@host'}, {'CCSDK_NACOS_PASSWORD':'private\nvalue'}):
            with self.subTest(changes=list(changes)), self.assertRaises(ValueError) as caught:
                writer.render(self.environment()|changes)
            self.assertNotIn('private',str(caught.exception))

    @unittest.skipUnless(os.name == 'posix', 'Linux deployment file permissions')
    def test_generates_only_bootstrap_file_at_selected_location(self):
        script=Path(__file__).with_name('write-env.py').resolve()
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            environment={**os.environ,**self.environment(),'CCSDK_CONFIG_DIRECTORY':'from env'}
            result=subprocess.run([sys.executable,str(script)],cwd=root,env=environment,capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            output=root/'from env/runtime.env'
            self.assertEqual(output.read_text(),writer.render(environment))
            self.assertEqual(output.stat().st_mode & 0o777,0o600)

    @unittest.skipUnless(os.name == "posix" and shutil.which("flock"), "Linux deployment shell and lock")
    def test_deploy_uses_configured_paths_and_shared_lock(self):
        import fcntl

        script = Path(__file__).with_name("deploy.sh").resolve()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            binary = root / "bin"
            binary.mkdir()
            docker = binary / "docker"
            docker.write_text(
                '#!/bin/sh\n'
                'if [ "$1" = version ]; then echo linux/amd64; exit 0; fi\n'
                'if [ "$1" = image ]; then exit 0; fi\n'
                'if [ "$1" = compose ] && [ "$2" = version ]; then echo 2.30.1; exit 0; fi\n'
                'if [ "$1" = compose ]; then\n'
                '  compose_args="$*"\n'
                '  shift\n'
                '  while [ "$1" = "-f" ]; do shift 2; done\n'
                '  if [ "$1" = ps ]; then echo test-container-id; exit 0; fi\n'
                'fi\n'
                'if [ "$1" = inspect ]; then\n'
                '  case "$3" in\n'
                '    *".Config.Init"*) echo true;;\n'
                '    *".HostConfig.PidsLimit"*) echo 4096;;\n'
                '    *".HostConfig.Memory"*) echo 2147483648;;\n'
                '  esac\n'
                '  exit 0\n'
                'fi\n'
                'printf "%s|%s|%s\\n" "$CCSDK_ENV_FILE" "$CCSDK_CONFIG_DIRECTORY" "${compose_args:-$*}" >> "$TEST_DOCKER_LOG"\n'
            )
            docker.chmod(0o700)
            config = root / "config with spaces"
            log = root / "docker.log"
            environment = {**os.environ, "PATH": str(binary) + os.pathsep + os.environ["PATH"],
                           "CCSDK_IMAGE": "test:paths", "CCSDK_GENERATE_ENV": "0",
                           "CCSDK_PULL_IMAGE": "0",
                           "CCSDK_WITH_APPLICATION": "1",
                           "CCSDK_CONFIG_DIRECTORY": os.path.relpath(config, script.parent), "TEST_DOCKER_LOG": str(log)}
            for key in ("CCSDK_ENV_FILE", "CCSDK_DEPLOY_LOCK_FILE"):
                environment.pop(key, None)
            result = subprocess.run(["sh", str(script)], cwd=root, env=environment, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            calls = log.read_text().splitlines()
            self.assertTrue(all(line.startswith(f"{config}/runtime.env|{config}|") for line in calls))
            self.assertIn("-f compose.application.yaml config --quiet", calls[0])
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
