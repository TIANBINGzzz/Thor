"""Validate deployment configuration without printing values, then start one HTTP worker."""

import os
import sys
from urllib.parse import urlsplit


def validate_environment():
    required = ("ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL", "ANTHROPIC_MODEL", "CCSDK_RUNTIME_JWT_SECRET")
    invalid = [name for name in required if not os.environ.get(name, "").strip()]
    # JWT secret content is deployment-owned; only require a nonempty value.
    invalid.extend(name for name in required if name != "CCSDK_RUNTIME_JWT_SECRET"
                   and any(marker in os.environ.get(name, "").lower()
                           for marker in ("your_", "replace-with")))
    try:
        url = urlsplit(os.environ.get("ANTHROPIC_BASE_URL", ""))
        if url.scheme != "https" or not url.hostname or url.username or url.password:
            invalid.append("ANTHROPIC_BASE_URL")
    except ValueError:
        invalid.append("ANTHROPIC_BASE_URL")
    if invalid:
        raise SystemExit("Missing or invalid deployment settings: " + ", ".join(sorted(set(invalid))))


if __name__ == "__main__":
    validate_environment()
    if sys.argv[1:] == ["--check"]:
        print("Deployment environment check passed.")
    else:
        os.execv(sys.executable, [sys.executable, "-m", "uvicorn", "server:app", "--app-dir", "python",
                                "--host", "0.0.0.0", "--port", "4310", "--workers", "1"])
