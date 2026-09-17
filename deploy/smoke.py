"""Verify a deployed Runtime with a signed Run and a real model request; log no credentials."""

import asyncio
import json
import os
from pathlib import Path
import sys
import time
import uuid

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python"))
from runtime.auth import encode_hs256_jwt


async def main():
    suffix = uuid.uuid4().hex
    body = {"protocol": "agent-run/v1", "runId": "deploy-" + suffix,
            "messageId": "message-" + suffix, "businessSessionId": "deploy-" + suffix,
            "capabilityRef": "conversation", "input": {"text": "Compute 17 * 23. Reply only with the number. Do not use tools."}}
    now = int(time.time())
    claims = {"iss": os.environ.get("CCSDK_RUNTIME_JWT_ISSUER", "string-ai-center-service"),
              "aud": os.environ.get("CCSDK_RUNTIME_JWT_AUDIENCE", "ccsdk-runtime"),
              "iat": now, "exp": now + 600, "jti": suffix,
              "sub": "deployment-check", "tenant": "deployment-check",
              **{key: body[key] for key in ("runId", "messageId", "businessSessionId", "capabilityRef")}}

    def headers(scope):
        token = encode_hs256_jwt({**claims, "scope": scope}, os.environ["CCSDK_RUNTIME_JWT_SECRET"])
        return {"Authorization": "Bearer " + token}

    # Loopback refers to this running container, not the deployment host.
    async with httpx.AsyncClient(base_url=os.environ.get("CCSDK_SMOKE_BASE_URL", "http://127.0.0.1:4310"),
                                 timeout=240, trust_env=False) as client:
        if (await client.get("/health")).status_code != 200:
            raise ValueError("Health check failed")
        route = "/internal/v1/runs/" + body["runId"]
        if (await client.post("/internal/v1/runs", json=body)).status_code != 401:
            raise ValueError("Unauthenticated access was not rejected")
        response = await client.post("/internal/v1/runs", json=body, headers=headers("run.execute"))
        if response.status_code != 202:
            raise ValueError("Signed Run was not accepted")
        try:
            events = []
            async with asyncio.timeout(240):
                async with client.stream("GET", route + "/events", headers=headers("run.read")) as stream:
                    stream.raise_for_status()
                    async for line in stream.aiter_lines():
                        if line.startswith("data: "):
                            events.append(json.loads(line[6:]))
            text = "".join(event.get("payload", {}).get("textDelta", "") for event in events)
            if not any(event["type"] == "run.completed" for event in events) or "391" not in text:
                raise ValueError("Model Run or expected response check failed")
            sequences = [event["sequence"] for event in events]
            if sequences != sorted(set(sequences)):
                raise ValueError("SSE sequence check failed")
        except Exception:
            try:
                await client.post(route + "/cancel", headers=headers("run.cancel"))
            except httpx.HTTPError:
                pass
            raise
    print("Smoke passed: HTTP health, authentication, signed Run, real model response and ordered SSE.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception:
        sys.exit("Deployment smoke failed; inspect Runtime with authorized diagnostics. Response bodies and credentials withheld.")
