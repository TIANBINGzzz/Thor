"""Command-line entry point for one Agent run."""

from __future__ import annotations

import argparse
import asyncio
import os

from runtime.process import prompt_without_workflow_prefix, stream_agent, workflow_name_from_prompt


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("prompt", nargs="*", help="Agent prompt")
    parser.add_argument("--db-demo", action="store_true")
    args = parser.parse_args()
    if args.db_demo:
        os.environ["DB_DEMO"] = "true"
    prompt = " ".join(args.prompt) or "你好，请用一句话介绍你自己。"
    workflow_name = workflow_name_from_prompt(prompt)
    agent_prompt = prompt_without_workflow_prefix(prompt) if workflow_name else prompt
    error_message = None
    async for event in stream_agent({"prompt": agent_prompt, "workflow_name": workflow_name}):
        if event.get("type") == "text" and event.get("scope", "main") == "main":
            print(event.get("text", ""), flush=True)
        if event.get("type") == "error":
            error_message = event.get("message") or "调用失败"
    if error_message:
        raise RuntimeError(error_message)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
