"""Render deployment files from task environment variables without logging values."""

import argparse
import base64
import binascii
import json
import os
import re
from pathlib import Path
import tempfile
from urllib.parse import urlsplit


RUNTIME_KEYS = (
    "CCSDK_IMAGE_BASE_URL", "CCSDK_IMAGE_API_KEY", "CCSDK_IMAGE_MODEL",
    "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL", "ANTHROPIC_MODEL", "SCRIBE_MODELS",
    "ANTHROPIC_DEFAULT_HAIKU_MODEL", "ANTHROPIC_DEFAULT_SONNET_MODEL",
    "ANTHROPIC_DEFAULT_OPUS_MODEL", "CLAUDE_CODE_SUBAGENT_MODEL",
    "CCSDK_RUNTIME_JWT_SECRET", "CCSDK_RUNTIME_JWT_AUDIENCE", "CCSDK_RUNTIME_JWT_ISSUER",
    "CCSDK_FILE_BROKER_URL", "CCSDK_FILE_BROKER_ALLOWED_HOSTS", "CCSDK_FILE_BROKER_AUTH_MODE",
    "CCSDK_FILE_BROKER_SERVICE_TOKEN", "CCSDK_FILE_BROKER_CA",
    "CCSDK_FILE_BROKER_CLIENT_CERT", "CCSDK_FILE_BROKER_CLIENT_KEY",
    "CCSDK_FILE_BROKER_TIMEOUT_MS", "CCSDK_FILE_PREPARE_TIMEOUT_MS", "CCSDK_FILE_MAX_BYTES",
    "CCSDK_RUN_EXECUTION_TIMEOUT_MS", "CCSDK_CLIENT_QUEUE_TIMEOUT_MS",
    "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY",
    "CCSDK_CLIENT_CAPABILITIES", "CCSDK_BUSINESS_MCP_CAPABILITIES", "SCRIBE_MAX_TURNS",
)
REQUIRED_KEYS = ("ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL", "ANTHROPIC_MODEL", "CCSDK_RUNTIME_JWT_SECRET")
DATABASE_KEYS = ("CCSDK_DATABASES_JSON", "CCSDK_DATABASE_CERTIFICATES_JSON")


def certificates(environment):
    values = json.loads(environment.get('CCSDK_DATABASE_CERTIFICATES_JSON', '{}'))
    if not isinstance(values, dict) or any(
        not re.fullmatch(r'[A-Za-z0-9_-]+\.pem', name) or not isinstance(value, str) or not value
        for name, value in values.items()
    ):
        raise ValueError('Invalid database certificates')
    return values


def parse_bundle(content):
    try:
        environment = json.loads(content)
    except (ValueError, UnicodeError):
        raise ValueError("Deployment bundle must contain UTF-8 JSON") from None
    if not isinstance(environment, dict) or not all(
        key in RUNTIME_KEYS + DATABASE_KEYS and isinstance(value, str)
        for key, value in environment.items()
    ):
        raise ValueError("Deployment bundle must map allowed variable names to strings")
    render(environment)
    if any(key in environment for key in DATABASE_KEYS):
        render(environment, database=True)
    return environment


def load_environment(environment):
    if "CCSDK_DEPLOY_ENV_B64" not in environment:
        return environment
    try:
        content = base64.b64decode(environment["CCSDK_DEPLOY_ENV_B64"], validate=True)
    except (ValueError, binascii.Error):
        raise ValueError("CCSDK_DEPLOY_ENV_B64 must be single-line Base64 from encode-secret.py") from None
    return parse_bundle(content)


def render(environment, *, database=False):
    if database:
        try:
            config = json.loads(environment["CCSDK_DATABASES_JSON"])
            if (not isinstance(config, dict) or config.get('version') != 1
                    or not isinstance(config.get('sources'), dict) or not config['sources']):
                raise ValueError()
            certs = certificates(environment)
            for source, entry in config['sources'].items():
                if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,95}', source) or not isinstance(entry, dict):
                    raise ValueError()
                connection, policy = entry.get('connection'), entry.get('policy')
                if any(not isinstance(v, dict) or not v or 'source_key' in v for v in (connection, policy)):
                    raise ValueError()
                if connection.get('driver') != 'mysql+pymysql' or any(
                    not isinstance(connection.get(k), str) or not connection[k]
                    for k in ('host', 'database', 'username', 'password')
                ):
                    raise ValueError()
                tls = connection.get('tls', {})
                mode = tls.get('mode', 'verify_identity')
                if mode not in ('verify_identity', 'disabled'):
                    raise ValueError()
                if mode == 'verify_identity' and (tls.get('verify_identity') is not True
                        or tls.get('ca_file') not in {'certificates/' + name for name in certs}):
                    raise ValueError()
            return json.dumps(config, ensure_ascii=False, indent=2) + "\n"
        except (KeyError, ValueError, TypeError, AttributeError):
            raise ValueError("Invalid protected data configuration or missing database secrets") from None
    keys = DATABASE_KEYS if database else RUNTIME_KEYS
    required = DATABASE_KEYS if database else REQUIRED_KEYS
    for key in required:
        if not environment.get(key, "").strip():
            raise ValueError("Missing deployment variable: " + key)
    if not database:
        try:
            url = urlsplit(environment["ANTHROPIC_BASE_URL"])
            valid_url = url.scheme == "https" and url.hostname and not url.username and not url.password
        except ValueError:
            valid_url = False
        if not valid_url:
            raise ValueError("ANTHROPIC_BASE_URL must be an HTTPS endpoint without credentials")
    lines = []
    for key in keys:
        if key not in environment:
            continue
        value = environment[key]
        if any(char in value for char in ("\r", "\n", "\x00")):
            raise ValueError("Multiline or NUL deployment variable: " + key)
        lines.append(key + "=" + value + "\n")
    return "".join(lines)


def atomic_write(path, content, *, database=False):
    descriptor, temporary = tempfile.mkstemp(prefix=".env-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        if database:
            os.chown(temporary, 10001, 10001)
        os.chmod(temporary, 0o400 if database else 0o600)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=os.environ.get("CCSDK_CONFIG_DIRECTORY") or None)
    parser.add_argument("--database", action="store_true")
    parser.add_argument("--list-keys", action="store_true")
    args = parser.parse_args()
    if args.list_keys:
        print("\n".join(RUNTIME_KEYS + DATABASE_KEYS))
        return
    if args.directory is None:
        parser.error("Set --directory or CCSDK_CONFIG_DIRECTORY")
    try:
        environment = load_environment(os.environ)
        runtime = render(environment)
        database = render(environment, database=True) if args.database else None
        if os.name != "posix":
            raise ValueError("Run on the Linux deployment host to enforce file ownership and permissions")
        if args.database and os.geteuid() != 0:
            raise ValueError("Database file generation requires root to set container UID 10001")
        args.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(args.directory, 0o700)
        atomic_write(args.directory / "runtime.env", runtime)
        if database is not None:
            # The container UID must traverse the mounted directory; runtime.env stays root-only.
            os.chown(args.directory, 0, 10001)
            os.chmod(args.directory, 0o750)
            directory = args.directory / "certificates"
            directory.mkdir(mode=0o700, exist_ok=True)
            os.chown(directory, 10001, 10001)
            os.chmod(directory, 0o700)
            for name, content in certificates(environment).items():
                atomic_write(directory / name, content, database=True)
            atomic_write(args.directory / "databases.json", database, database=True)
    except (ValueError, OSError) as error:
        if isinstance(error, ValueError):
            parser.exit(1, str(error) + "\n")
        parser.exit(1, "Cannot write deployment files; check directory permissions and ownership.\n")
    print("Deployment env files generated; values withheld.")


if __name__ == "__main__":
    main()
