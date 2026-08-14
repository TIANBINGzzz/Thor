import { randomBytes } from "node:crypto";
import { spawn } from "node:child_process";
import dotenv from "dotenv";

dotenv.config({ override: true, quiet: true });

const token = process.env.SCRIBE_TOKEN || randomBytes(24).toString("hex");
const port = process.env.SCRIBE_PORT || "4310";
const env = {
  ...process.env,
  SCRIBE_TOKEN: token,
  SCRIBE_PORT: port,
  AGENT_SERVICE_URL: process.env.AGENT_SERVICE_URL || `http://127.0.0.1:${port}`,
};
const npmCli = process.env.npm_execpath;
if (!npmCli) throw new Error("请通过 npm run ui 启动界面");

const backend = spawn(process.execPath, ["app/server.mjs"], { env, stdio: "inherit" });
const frontend = spawn(process.execPath, [npmCli, "--prefix", "web", "run", "dev"], { env, stdio: "inherit" });
const children = [backend, frontend];
let closing = false;

function shutdown(code = 0) {
  if (closing) return;
  closing = true;
  for (const child of children) {
    if (!child.killed) child.kill("SIGTERM");
  }
  process.exitCode = code;
}

for (const child of children) {
  child.on("exit", (code, signal) => {
    if (!closing) shutdown(code ?? (signal ? 1 : 0));
  });
  child.on("error", () => shutdown(1));
}

process.on("SIGINT", () => shutdown(0));
process.on("SIGTERM", () => shutdown(0));
