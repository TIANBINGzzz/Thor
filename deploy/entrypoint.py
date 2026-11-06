"""Validate deployment configuration without printing values, then start one HTTP worker."""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'python'))


def validate_environment():
    """使用正式引导链路校验 Nacos；仅输出稳定错误码。"""
    from runtime.bootstrap import initialize_runtime
    try:
        initialize_runtime()
    except ValueError as error:
        raise SystemExit('Deployment configuration failed: ' + str(error)) from None


if __name__ == "__main__":
    validate_environment()
    if sys.argv[1:] == ["--check"]:
        print("Deployment environment check passed.")
    else:
        import uvicorn
        from runtime.application_config import application_settings
        settings = application_settings()['server']
        uvicorn.run('server:app', host=settings['host'], port=settings['port'], workers=1)
