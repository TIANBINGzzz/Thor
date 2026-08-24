import { spawn } from "node:child_process";
import { createInterface } from "node:readline";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const PROJECT_ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const WORKER = join(PROJECT_ROOT, "python", "agent_worker.py");

function pythonCommand() {
  if (process.env.PYTHON_BIN?.trim()) {
    return { command: process.env.PYTHON_BIN.trim(), args: [] };
  }
  return process.platform === "win32"
    ? { command: "py", args: ["-3"] }
    : { command: "python3", args: [] };
}

/**
 * Run one Python Agent SDK query. The callback receives the same compact event
 * objects that the web SSE layer already consumes.
 */
export function runPythonAgent(payload, { onEvent, signal } = {}) {
  return new Promise((resolve, reject) => {
    const python = pythonCommand();
    const child = spawn(python.command, [...python.args, WORKER], {
      cwd: PROJECT_ROOT,
      env: process.env,
      stdio: ["pipe", "pipe", "pipe"],
      windowsHide: true,
    });
    const lines = createInterface({ input: child.stdout });
    let settled = false;
    let sawWorkerDone = false;

    const finish = (error) => {
      if (settled) return;
      settled = true;
      lines.close();
      if (error) reject(error);
      else resolve();
    };

    lines.on("line", (line) => {
      if (!line.trim()) return;
      let event;
      try {
        event = JSON.parse(line);
      } catch {
        return;
      }
      if (event.type === "worker_done") {
        sawWorkerDone = true;
        return;
      }
      if (event.type === "worker_error") {
        finish(new Error(event.message || "Python Agent 执行失败"));
        return;
      }
      onEvent?.(event);
    });

    child.stderr.on("data", (chunk) => {
      const message = String(chunk).trim();
      if (message) console.error(`[python-agent] ${message}`);
    });
    child.once("error", finish);
    child.once("exit", (code, childSignal) => {
      if (signal?.aborted) {
        finish();
        return;
      }
      if (code === 0 && sawWorkerDone) {
        finish();
        return;
      }
      finish(new Error(`Python Agent worker 退出（code=${code}, signal=${childSignal || "none"}）`));
    });

    const abort = () => {
      if (!child.killed) child.kill();
    };
    if (signal) {
      if (signal.aborted) abort();
      else signal.addEventListener("abort", abort, { once: true });
    }

    child.stdin.end(JSON.stringify(payload) + "\n");
  });
}
