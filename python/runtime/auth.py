"""Small dependency-free HS256 JWT verifier for Java -> Runtime calls.

This module authenticates the caller and binds Run or session-read grants. It does not
look up tenants or users in a database; the Java control plane remains the
authority for those resources.  The in-memory replay cache is intentionally a
single-process MVP and must be replaced by Redis/another atomic store when the
Runtime is deployed with multiple instances.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import math
import threading
import time
from collections.abc import Mapping
from typing import Any


class JWTError(ValueError):
    """Raised when a JWT is malformed, unauthenticated, expired or replayed."""


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64decode(value: str) -> bytes:
    if not isinstance(value, str) or not value or any(char not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_" for char in value):
        raise JWTError("invalid JWT encoding")
    try:
        return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except (ValueError, base64.binascii.Error) as error:
        raise JWTError("invalid JWT encoding") from error


def _json_segment(value: str, name: str) -> dict[str, Any]:
    try:
        decoded = json.loads(_b64decode(value).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise JWTError(f"invalid JWT {name}") from error
    if not isinstance(decoded, dict):
        raise JWTError(f"JWT {name} must be an object")
    return decoded


def encode_hs256_jwt(claims: Mapping[str, Any], secret: str | bytes) -> str:
    """接收 claims 和共享密钥，返回 HS256 签名 JWT，主要供适配器测试使用。"""
    if not isinstance(claims, Mapping):
        raise TypeError("claims must be a mapping")
    secret_bytes = secret.encode("utf-8") if isinstance(secret, str) else bytes(secret)
    if not secret_bytes:
        raise ValueError("JWT secret must not be empty")
    header = {"alg": "HS256", "typ": "JWT"}
    encoded_header = _b64encode(json.dumps(header, separators=(",", ":")).encode("utf-8"))
    encoded_claims = _b64encode(json.dumps(dict(claims), ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    signing_input = f"{encoded_header}.{encoded_claims}".encode("ascii")
    signature = hmac.new(secret_bytes, signing_input, hashlib.sha256).digest()
    return f"{encoded_header}.{encoded_claims}.{_b64encode(signature)}"


def sign_hs256(claims: Mapping[str, Any], secret: str | bytes) -> str:
    """Alias with a shorter name for adapter tests and local tooling."""
    return encode_hs256_jwt(claims, secret)


class ReplayCache:
    """Thread-safe TTL cache for one-time JWT ``jti`` values."""

    def __init__(self, *, max_entries: int = 10_000) -> None:
        if max_entries < 1:
            raise ValueError("max_entries must be positive")
        self.max_entries = max_entries
        self._values: dict[str, float] = {}
        self._lock = threading.Lock()

    def check_and_mark(self, jti: str, *, ttl_seconds: float, now: float | None = None) -> bool:
        """检查并登记指定 jti 的有效期，首次登记返回 True，重复使用返回 False；缓存满时淘汰最早过期项。"""
        current = time.time() if now is None else float(now)
        expiry = current + max(0.001, float(ttl_seconds))
        with self._lock:
            for key, value in list(self._values.items()):
                if value <= current:
                    self._values.pop(key, None)
            if jti in self._values:
                return False
            if len(self._values) >= self.max_entries:
                oldest = min(self._values, key=self._values.get)
                self._values.pop(oldest, None)
            self._values[jti] = expiry
            return True

    def clear(self) -> None:
        with self._lock:
            self._values.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._values)


def _number(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise JWTError(f"JWT {name} must be numeric")
    return float(value)


def _audience_matches(value: Any, expected: str) -> bool:
    if isinstance(value, str):
        return hmac.compare_digest(value, expected)
    if isinstance(value, list):
        return any(isinstance(item, str) and hmac.compare_digest(item, expected) for item in value)
    return False


def _verify_signed_claims(
    token: str, secret: str | bytes, *, audience: str, issuer: str | None,
    expected_scope: str, required_claims: tuple[str, ...], now: float | None = None,
    leeway_seconds: float = 5.0,
) -> dict[str, Any]:
    if not isinstance(token, str) or token.count(".") != 2:
        raise JWTError("malformed JWT")
    encoded_header, encoded_claims, encoded_signature = token.split(".")
    header = _json_segment(encoded_header, "header")
    if header.get("alg") != "HS256" or header.get("typ", "JWT") != "JWT":
        raise JWTError("unsupported JWT algorithm")
    signature = _b64decode(encoded_signature)
    secret_bytes = secret.encode("utf-8") if isinstance(secret, str) else bytes(secret)
    if not secret_bytes:
        raise JWTError("JWT secret must not be empty")
    expected = hmac.new(
        secret_bytes,
        f"{encoded_header}.{encoded_claims}".encode("ascii"),
        hashlib.sha256,
    ).digest()
    if not hmac.compare_digest(signature, expected):
        raise JWTError("invalid JWT signature")
    claims = _json_segment(encoded_claims, "claims")

    current = time.time() if now is None else float(now)
    leeway = max(0.0, float(leeway_seconds))
    if not _audience_matches(claims.get("aud"), audience):
        raise JWTError("invalid JWT audience")
    exp = _number(claims.get("exp"), "exp")
    issued_at = _number(claims.get("iat"), "iat")
    if exp <= current - leeway:
        raise JWTError("JWT has expired")
    if issued_at > current + leeway:
        raise JWTError("JWT was issued in the future")
    if exp <= issued_at:
        raise JWTError("JWT expiration must follow iat")
    if issuer is not None and claims.get("iss") != issuer:
        raise JWTError("invalid JWT issuer")

    for name in required_claims:
        value = claims.get(name)
        if not isinstance(value, str) or not value.strip():
            raise JWTError(f"JWT {name} is required")

    scope = claims.get("scope")
    if isinstance(scope, str):
        scopes = {scope}
    elif isinstance(scope, list) and all(isinstance(item, str) for item in scope):
        scopes = set(scope)
    else:
        raise JWTError("JWT scope is required")
    if expected_scope and expected_scope not in scopes:
        raise JWTError("JWT scope is not allowed")

    return claims


def verify_session_read_jwt(
    token: str, secret: str | bytes, *, business_session_id: str,
    audience: str = "ccsdk-runtime", issuer: str | None = None,
) -> dict[str, Any]:
    """校验Java签发的会话读取授权；只读分页可在有效期内重复使用。"""
    claims = _verify_signed_claims(
        token, secret, audience=audience, issuer=issuer, expected_scope="session.read",
        required_claims=("sub", "tenant", "jti", "businessSessionId"),
    )
    if claims["businessSessionId"] != business_session_id:
        raise JWTError("businessSessionId mismatch")
    return claims


def verify_run_jwt(
    token: str,
    secret: str | bytes,
    *,
    run_id: str | None = None,
    capability_ref: str | None = None,
    turn_id: str | None = None,
    business_session_id: str | None = None,
    message_id: str | None = None,
    body: Mapping[str, Any] | Any | None = None,
    audience: str = "ccsdk-runtime",
    expected_scope: str = "run.execute",
    issuer: str | None = None,
    replay_cache: ReplayCache | None = None,
    consume_jti: bool = True,
    now: float | None = None,
    leeway_seconds: float = 5.0,
) -> dict[str, Any]:
    """接收 JWT、共享密钥及请求绑定条件，校验签名、时效、权限和业务绑定后返回 claims。

    body 可为字典或 AgentRunRequest；启用重放检查时，仅在全部验证通过后登记 jti。
    """
    claims = _verify_signed_claims(
        token, secret, audience=audience, issuer=issuer, expected_scope=expected_scope,
        required_claims=("sub", "tenant", "jti", "runId", "capabilityRef"),
        now=now, leeway_seconds=leeway_seconds,
    )
    current = time.time() if now is None else float(now)
    leeway = max(0.0, float(leeway_seconds))
    exp = float(claims["exp"])

    body_run_id: str | None = run_id
    body_capability: str | None = capability_ref
    body_turn_id: str | None = turn_id
    body_business_session_id: str | None = business_session_id
    body_message_id: str | None = message_id
    if body is not None:
        if hasattr(body, "run_id"):
            body_run_id = getattr(body, "run_id")
            body_capability = getattr(body, "capability_ref", body_capability)
            body_turn_id = getattr(body, "turn_id", body_turn_id)
            body_business_session_id = getattr(body, "business_session_id", body_business_session_id)
            body_message_id = getattr(body, "message_id", body_message_id)
        elif isinstance(body, Mapping):
            body_run_id = body.get("runId", body.get("run_id", body_run_id))
            body_capability = body.get("capabilityRef", body.get("capability_ref", body_capability))
            body_turn_id = body.get("turnId", body.get("turn_id", body_turn_id))
            body_business_session_id = body.get("businessSessionId", body.get("business_session_id", body_business_session_id))
            body_message_id = body.get("messageId", body.get("message_id", body_message_id))
            if body_capability is None:
                execution = body.get("execution")
                if isinstance(execution, Mapping):
                    workflow = execution.get("workflowRef")
                    if isinstance(workflow, Mapping):
                        body_capability = workflow.get("id")
                    elif isinstance(workflow, str):
                        body_capability = workflow
    if body_run_id is not None and body_run_id != claims["runId"]:
        raise JWTError("runId mismatch")
    if body_capability != claims.get("capabilityRef"):
        raise JWTError("capabilityRef mismatch")
    for claim_name, body_value, label in (
        ("turnId", body_turn_id, "turnId"),
        ("businessSessionId", body_business_session_id, "businessSessionId"),
        ("messageId", body_message_id, "messageId"),
    ):
        claim_value = claims.get(claim_name)
        if body_value is not None and claim_value != body_value:
            raise JWTError(f"{label} mismatch")

    if consume_jti:
        cache = replay_cache if replay_cache is not None else _DEFAULT_REPLAY_CACHE
        ttl = max(0.001, exp - current + leeway)
        if not cache.check_and_mark(claims["jti"], ttl_seconds=ttl, now=current):
            raise JWTError("JWT jti has already been used")
    return claims


def verify_hs256_jwt(*args: Any, **kwargs: Any) -> dict[str, Any]:
    """Compatibility alias for callers that use the algorithm in the name."""
    return verify_run_jwt(*args, **kwargs)


_DEFAULT_REPLAY_CACHE = ReplayCache()
