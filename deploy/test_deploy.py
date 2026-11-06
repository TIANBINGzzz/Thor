"""完整 YAML 挂载及部署锁的 Linux 回归。"""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


class DeploymentYamlTests(unittest.TestCase):
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
                'printf "%s|%s|%s\\n" "$CCSDK_APPLICATION_FILE" "$CCSDK_CONFIG_DIRECTORY" "${compose_args:-$*}" >> "$TEST_DOCKER_LOG"\n'
            )
            docker.chmod(0o700)
            config = root / "config with spaces"
            config.mkdir()
            (config / "application.production.yml").write_text("test application file")
            log = root / "docker.log"
            environment = {**os.environ, "PATH": str(binary) + os.pathsep + os.environ["PATH"],
                           "CCSDK_IMAGE": "test:paths",
                           "CCSDK_PULL_IMAGE": "0",

                           "CCSDK_CONFIG_DIRECTORY": os.path.relpath(config, script.parent), "TEST_DOCKER_LOG": str(log)}
            for key in ("CCSDK_APPLICATION_FILE", "CCSDK_DEPLOY_LOCK_FILE"):
                environment.pop(key, None)
            result = subprocess.run(["sh", str(script)], cwd=root, env=environment, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            calls = log.read_text().splitlines()
            self.assertTrue(all(line.startswith(f"{config}/application.production.yml|{config}|") for line in calls))
            self.assertIn("-f compose.yaml config --quiet", calls[0])
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


if __name__ == '__main__':
    unittest.main()
