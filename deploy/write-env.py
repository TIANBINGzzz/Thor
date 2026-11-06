"""Render deployment files from task environment variables without logging values."""

import argparse
import base64
import binascii
import json
import os
from pathlib import Path
import tempfile
from urllib.parse import urlsplit


RUNTIME_KEYS = (
    'CCSDK_NACOS_URL', 'CCSDK_NACOS_NAMESPACE', 'CCSDK_NACOS_GROUP', 'CCSDK_NACOS_DATA_ID',
    'CCSDK_NACOS_USERNAME', 'CCSDK_NACOS_PASSWORD',
    'HTTP_PROXY', 'HTTPS_PROXY', 'NO_PROXY',
    'CCSDK_OFFICECLI_PATH', 'CCSDK_LIBREOFFICE_PATH', 'CCSDK_UNO_PYTHON', 'CCSDK_RENDER_IMAGE',
)
REQUIRED_KEYS = ('CCSDK_NACOS_URL',)


def parse_bundle(content):
    try:
        environment = json.loads(content)
    except (ValueError, UnicodeError):
        raise ValueError("Deployment bundle must contain UTF-8 JSON") from None
    if not isinstance(environment, dict) or not all(
        key in RUNTIME_KEYS and isinstance(value, str)
        for key, value in environment.items()
    ):
        raise ValueError("Deployment bundle must map allowed variable names to strings")
    render(environment)
    return environment


def load_environment(environment):
    if "CCSDK_DEPLOY_ENV_B64" not in environment:
        return environment
    try:
        content = base64.b64decode(environment["CCSDK_DEPLOY_ENV_B64"], validate=True)
    except (ValueError, binascii.Error):
        raise ValueError("CCSDK_DEPLOY_ENV_B64 must be single-line Base64 from encode-secret.py") from None
    return parse_bundle(content)


def render(environment):
    """只生成 Nacos 引导及进程参数，客户秘密不进入 runtime.env。"""
    for key in REQUIRED_KEYS:
        if not environment.get(key, '').strip():
            raise ValueError('Missing deployment variable: ' + key)
    address = environment['CCSDK_NACOS_URL']
    try:
        url = urlsplit(address if '://' in address else 'http://' + address)
        if url.scheme not in {'http', 'https'} or not url.hostname or url.username or url.password or url.query or url.fragment:
            raise ValueError()
    except ValueError:
        raise ValueError('Invalid Nacos endpoint') from None
    if bool(environment.get('CCSDK_NACOS_USERNAME')) != bool(environment.get('CCSDK_NACOS_PASSWORD')):
        raise ValueError('Incomplete Nacos credentials')
    lines = []
    for key in RUNTIME_KEYS:
        if key not in environment:
            continue
        value = environment[key]
        if not isinstance(value, str) or any(c in value for c in ('\r', '\n', '\x00')):
            raise ValueError('Multiline or NUL deployment variable: ' + key)
        lines.append(key + '=' + value + '\n')
    return ''.join(lines)


def atomic_write(path, content):
    descriptor, temporary = tempfile.mkstemp(prefix=".env-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=os.environ.get("CCSDK_CONFIG_DIRECTORY") or None)
    parser.add_argument("--list-keys", action="store_true")
    args = parser.parse_args()
    if args.list_keys:
        print("\n".join(RUNTIME_KEYS))
        return
    if args.directory is None:
        parser.error("Set --directory or CCSDK_CONFIG_DIRECTORY")
    try:
        environment = load_environment(os.environ)
        runtime = render(environment)
        if os.name != "posix":
            raise ValueError("Run on the Linux deployment host to enforce file ownership and permissions")
        args.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(args.directory, 0o700)
        atomic_write(args.directory / "runtime.env", runtime)
    except (ValueError, OSError) as error:
        if isinstance(error, ValueError):
            parser.exit(1, str(error) + "\n")
        parser.exit(1, "Cannot write deployment files; check directory permissions and ownership.\n")
    print("Deployment env files generated; values withheld.")


if __name__ == "__main__":
    main()
