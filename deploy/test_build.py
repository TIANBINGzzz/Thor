"""Exercise the release shell with a fake Docker daemon; no network or image builds."""

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


@unittest.skipUnless(os.name == "posix", "POSIX build shell")
class BuildTests(unittest.TestCase):
    def run_build(self, mode):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "deploy").mkdir()
            (root / "bin").mkdir()
            for name in ("build.sh", "deploy.sh", "compose.yaml", "compose.database.yaml"):
                shutil.copyfile(Path(__file__).with_name(name), root / "deploy" / name)
            docker = root / "bin/docker"
            docker.write_text('''#!/bin/sh
set -eu
echo "$*" >> "$TEST_ROOT/calls"
case "$1" in
  version|info) echo linux/amd64 ;;
  pull)
    n=0
    if [ -f "$TEST_ROOT/attempts" ]; then n=$(cat "$TEST_ROOT/attempts"); fi
    n=$((n + 1)); echo "$n" > "$TEST_ROOT/attempts"
    if [ "$TEST_MODE" = pull-fails ]; then exit 1; fi
    if [ "$TEST_MODE" = retry ] && [ "$n" -lt 3 ]; then exit 1; fi
    ;;
  build) if [ "$TEST_MODE" = test-fails ]; then exit 1; fi ;;
  image) echo sha256:test ;;
  save) printf 'fake image' > "$3" ;;
  *) exit 2 ;;
esac
''', encoding="utf-8")
            docker.chmod(0o700)
            sleep = root / "bin/sleep"
            sleep.write_text('#!/bin/sh\necho "sleep $*" >> "$TEST_ROOT/calls"\n', encoding="utf-8")
            sleep.chmod(0o700)
            env = {**os.environ, "PATH": str(root / "bin") + os.pathsep + os.environ["PATH"],
                   "TEST_ROOT": str(root), "TEST_MODE": mode, "CCSDK_IMAGE": "test:release",
                   "CCSDK_OUTPUT_DIRECTORY": "dist/release", "NODE_IMAGE": "test:node",
                   "PYTHON_IMAGE": "test:python", "PIP_INDEX_URL": "https://example.com/simple"}
            result = subprocess.run(["sh", "deploy/build.sh"], cwd=root, env=env,
                                    capture_output=True, text=True)
            calls = (root / "calls").read_text().splitlines()
            packaged = (root / "dist/release/SHA256SUMS").exists()
            return result, calls, packaged

    def test_success_packages_only_after_both_builds(self):
        result, calls, packaged = self.run_build("success")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(packaged)
        builds = [line for line in calls if line.startswith("build ")]
        self.assertEqual(len(builds), 2)
        self.assertIn("--target test", builds[0])
        self.assertIn("--target runtime", builds[1])
        self.assertTrue(all("--pull=false" in line and "PIP_INDEX_URL=https://example.com/simple" in line for line in builds))

    def test_transient_pull_recovers(self):
        result, calls, packaged = self.run_build("retry")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(packaged)
        self.assertEqual(sum(line.startswith("pull ") for line in calls), 4)
        self.assertEqual([line for line in calls if line.startswith("sleep ")], ["sleep 10", "sleep 20"])

    def test_pull_exhaustion_never_builds_or_packages(self):
        result, calls, packaged = self.run_build("pull-fails")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("after 3 attempts", result.stderr)
        self.assertEqual(sum(line.startswith("pull ") for line in calls), 3)
        self.assertFalse(any(line.startswith("build ") for line in calls))
        self.assertFalse(packaged)

    def test_failed_tests_are_not_retried_or_published(self):
        result, calls, packaged = self.run_build("test-fails")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(sum(line.startswith("build ") for line in calls), 1)
        self.assertFalse(packaged)


if __name__ == "__main__":
    unittest.main()
