"""Start the Python API and the existing Next.js frontend as one local app."""

from __future__ import annotations

import os
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import time
from runtime.config import PROJECT_ROOT, load_runtime_environment


def _port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.25)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def _stop_tree(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    else:
        os.killpg(process.pid, signal.SIGTERM)


def main() -> int:
    load_runtime_environment()
    api_port = int(os.environ.get("SCRIBE_PORT", "4310"))
    web_port = int(os.environ.get("WEB_PORT", "3000"))
    occupied = [str(port) for port in (api_port, web_port) if _port_in_use(port)]
    if occupied:
        print(f"端口 {', '.join(occupied)} 已被占用。请先在旧服务终端按 Ctrl+C，再重新启动。", file=sys.stderr)
        return 1

    token = os.environ.get("SCRIBE_TOKEN") or secrets.token_hex(24)
    environment = dict(os.environ)
    environment.update({
        "SCRIBE_TOKEN": token,
        "SCRIBE_PORT": str(api_port),
        "PORT": str(web_port),
        "AGENT_SERVICE_URL": os.environ.get("AGENT_SERVICE_URL") or f"http://127.0.0.1:{api_port}",
    })
    npm = shutil.which("npm.cmd" if os.name == "nt" else "npm") or "npm"
    frontend_script = "dev" if "--dev" in sys.argv else "start"
    if frontend_script == "start":
        built = subprocess.run(
            [npm, "--prefix", "web", "run", "build"],
            cwd=str(PROJECT_ROOT),
            env=environment,
            check=False,
        )
        if built.returncode:
            return built.returncode
    process_kwargs = {
        "cwd": str(PROJECT_ROOT),
        "env": environment,
    }
    if os.name != "nt":
        process_kwargs["start_new_session"] = True
    else:
        process_kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    backend = subprocess.Popen([sys.executable, "python/server.py"], **process_kwargs)
    frontend = subprocess.Popen([npm, "--prefix", "web", "run", frontend_script], **process_kwargs)
    children = [backend, frontend]
    try:
        while all(child.poll() is None for child in children):
            time.sleep(0.2)
        return next((child.returncode for child in children if child.returncode is not None), 1) or 0
    except KeyboardInterrupt:
        return 0
    finally:
        for child in children:
            _stop_tree(child)


if __name__ == "__main__":
    raise SystemExit(main())
