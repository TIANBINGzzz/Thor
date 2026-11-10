"""获取内部测试环境的业务 Token。

59 使用认证服务现有的免验证码测试分支；appai 保持验证码校验，脚本只自动
获取图片和提交请求，验证码由操作者或 Agent 在本地识别后输入。appai 的
登录域名须取所选学校的 domainName，不使用平台主域名代替。Token 只写入忽略目录。
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "deploy" / "environments.local.md"
LOGIN_PATH = "/fwk_auth_service/login/"
CAPTCHA_PATH = "/fwk_auth_service/login/captcha/"


@dataclass(frozen=True)
class EnvironmentSettings:
    environment: str
    origin: str
    account: str
    password: str
    school: str | None = None
    domain_name: str | None = None


def _field(section: str, label: str, *, required: bool = True) -> str | None:
    match = re.search(rf"^\|\s*{re.escape(label)}\s*\|\s*`([^`]*)`\s*\|\s*$", section, re.MULTILINE)
    if match:
        return match.group(1)
    if required:
        raise ValueError(f"环境交接文件缺少字段：{label}")
    return None


def load_environment(config_path: Path, environment: str) -> EnvironmentSettings:
    """读取指定环境的登录信息，不打印任何凭据。"""
    text = config_path.read_text(encoding="utf-8")
    heading = "## 59 连接" if environment == "59" else "## appai 连接" if environment == "appai" else None
    if heading is None:
        raise ValueError("environment must be 59 or appai")
    try:
        section = text.split(heading, 1)[1].split("\n## ", 1)[0]
    except IndexError as error:
        raise ValueError(f"环境交接文件缺少环境：{environment}") from error
    webpage = re.search(r"^\|\s*业务网页\s*\|\s*(https?://[^|`\s]+)", section, re.MULTILINE)
    if not webpage:
        raise ValueError("环境交接文件缺少业务网页")
    origin = urllib.parse.urlsplit(webpage.group(1))._replace(path="", query="", fragment="").geturl().rstrip("/")
    return EnvironmentSettings(
        environment=environment,
        origin=origin,
        account=_field(section, "登录账号") or "",
        password=_field(section, "登录密码") or "",
        school=_field(section, "登录学校", required=False),
        domain_name=_field(section, "登录域名", required=environment == "appai"),
    )


def md5_password(password: str) -> str:
    return hashlib.md5(password.encode("utf-8")).hexdigest()


def build_login_payload(
    settings: EnvironmentSettings,
    *,
    captcha_id: str | None = None,
    captcha_code: str | None = None,
) -> dict[str, str]:
    """按环境选择服务端实际接受的登录参数。"""
    payload = {
        "userCode": settings.account,
        "password": md5_password(settings.password),
        "reUrl": settings.origin + "/ai_center_web/",
    }
    if settings.environment == "59":
        payload["type"] = "1"
        return payload
    if not captcha_id or not captcha_code:
        raise ValueError("appai 登录需要 captcha_id 和 captcha_code")
    payload.update({"imgId": captcha_id, "captcha": captcha_code.strip()})
    return payload


def _json_request(url: str, *, data: bytes | None = None, headers: dict[str, str] | None = None) -> dict[str, Any]:
    request = urllib.request.Request(url, data=data, headers=headers or {}, method="POST" if data is not None else "GET")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as error:
        body = error.read(512).decode("utf-8", "replace")
        raise RuntimeError(f"登录服务 HTTP {error.code}: {body[:160]}") from error


def fetch_captcha(settings: EnvironmentSettings) -> tuple[str, Path]:
    result = _json_request(settings.origin + CAPTCHA_PATH, headers=_login_headers(settings))
    data = result.get("data") or {}
    image = data.get("img")
    captcha_id = data.get("id")
    if result.get("state") != 200 or not captcha_id or not isinstance(image, str):
        raise RuntimeError("验证码接口未返回有效图片")
    encoded = image.split(",", 1)[1] if "," in image else image
    path = Path(tempfile.gettempdir()) / f"ccsdk-captcha-{settings.environment}.png"
    path.write_bytes(base64.b64decode(encoded))
    return str(captcha_id), path


def prompt_for_captcha(image_path: Path) -> str:
    """在本机打开验证码图片后读取一次人工确认结果。"""
    webbrowser.open(image_path.resolve().as_uri())
    return input(f"请输入验证码（图片已打开：{image_path}）：").strip()


def login(settings: EnvironmentSettings, *, captcha_id: str | None = None, captcha_code: str | None = None) -> dict[str, Any]:
    payload = build_login_payload(settings, captcha_id=captcha_id, captcha_code=captcha_code)
    result = _json_request(
        settings.origin + LOGIN_PATH,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={**_login_headers(settings), "Content-Type": "application/json"},
    )
    if result.get("state") != 200 or not (result.get("data") or {}).get("token"):
        raise RuntimeError(f"登录失败：state={result.get('state')} message={result.get('message')}")
    return result["data"]


def _login_headers(settings: EnvironmentSettings) -> dict[str, str]:
    """验证码和登录绑定同一学校；主域名上的同名账号可能属于不同租户。"""
    headers = {"Accept": "application/json"}
    if settings.environment == "appai":
        domain = (settings.domain_name or "").strip()
        if not domain:
            raise ValueError("appai 缺少登录域名，请填写所选学校的 domainName")
        headers["domain-name"] = domain
    return headers


def _default_output(environment: str) -> Path:
    return ROOT / "scratch" / "business-tokens" / f"{environment}.token"


def save_token(token: str, output: Path) -> None:
    """以同目录临时文件原子替换 Token，避免测试读到半截内容。"""
    value = token.strip()
    if not value:
        raise ValueError("登录响应未返回有效 Token")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=output.parent, delete=False) as handle:
        temporary = Path(handle.name)
        handle.write(value + "\n")
    try:
        os.replace(temporary, output)
        try:
            os.chmod(output, 0o600)
        except OSError:
            pass
    finally:
        temporary.unlink(missing_ok=True)


def load_saved_token(environment: str, output: Path | None = None) -> str:
    """读取已保存 Token；调用方负责避免回显或写入日志。"""
    path = output or _default_output(environment)
    value = path.read_text(encoding="utf-8").strip()
    if not value:
        raise RuntimeError(f"Token 文件为空：{path}")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="获取 59/appai 内部测试业务 Token")
    parser.add_argument("environment", choices=("59", "appai"))
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--captcha", help="appai 验证码；省略时自动打开图片并交互询问")
    args = parser.parse_args(argv)
    settings = load_environment(args.config, args.environment)
    captcha_id = captcha_code = None
    if settings.environment == "appai":
        captcha_id, image_path = fetch_captcha(settings)
        if not args.captcha:
            args.captcha = prompt_for_captcha(image_path)
        captcha_code = args.captcha
    data = login(settings, captcha_id=captcha_id, captcha_code=captcha_code)
    output = args.output or _default_output(settings.environment)
    save_token(data["token"], output)
    print(f"token_saved={output}")
    print(f"expires_at={data.get('expireTime')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
