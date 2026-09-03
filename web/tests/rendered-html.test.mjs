import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { readFile } from "node:fs/promises";
import net from "node:net";
import { fileURLToPath } from "node:url";
import test from "node:test";

const webRoot = fileURLToPath(new URL("..", import.meta.url));
const nextBin = fileURLToPath(new URL("../node_modules/next/dist/bin/next", import.meta.url));

async function freePort() {
  const server = net.createServer();
  await new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", resolve);
  });
  const address = server.address();
  const port = typeof address === "object" && address ? address.port : 0;
  await new Promise((resolve) => server.close(resolve));
  return port;
}

async function startNext(t) {
  const port = await freePort();
  let output = "";
  const child = spawn(process.execPath, [nextBin, "start", "-H", "127.0.0.1", "-p", String(port)], {
    cwd: webRoot,
    env: {
      ...process.env,
      AGENT_SERVICE_URL: "http://127.0.0.1:1",
      SCRIBE_TOKEN: "render-test-token",
    },
    stdio: ["ignore", "pipe", "pipe"],
  });
  child.stdout.on("data", (chunk) => { output += chunk; });
  child.stderr.on("data", (chunk) => { output += chunk; });
  t.after(() => child.kill());

  const url = `http://127.0.0.1:${port}/`;
  for (let attempt = 0; attempt < 100; attempt += 1) {
    if (child.exitCode !== null) throw new Error(`Next.js failed to start:\n${output}`);
    try {
      const response = await fetch(url, { headers: { accept: "text/html" } });
      if (response.ok) return response;
    } catch {
      // The server is still starting.
    }
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  throw new Error(`Timed out waiting for Next.js:\n${output}`);
}

test("server-renders the Thor chat shell", async (t) => {
  const response = await startNext(t);
  assert.equal(response.status, 200);
  assert.match(response.headers.get("content-type") ?? "", /^text\/html\b/i);

  const html = await response.text();
  assert.match(html, /<html lang="zh-CN">/);
  assert.match(html, /<title>Thor AI — AI 对话助手<\/title>/);
  assert.match(html, /历史会话/);
  assert.match(html, /deepseek-v4-flash/);
  assert.doesNotMatch(html, /文件最大 10 MB/);
  assert.doesNotMatch(html, /codex-preview|Building your site|Starter Project/i);
});

test("keeps the chat and statistics entry points", async () => {
  const [home, chat, stats, models, chatRoute, statsRoute, workspace, adapter] = await Promise.all([
    readFile(new URL("../app/page.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/chat/[sessionId]/page.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/stats/page.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/lib/models.ts", import.meta.url), "utf8"),
    readFile(new URL("../app/api/sessions/[id]/chat/route.ts", import.meta.url), "utf8"),
    readFile(new URL("../app/api/stats/route.ts", import.meta.url), "utf8"),
    readFile(new URL("../app/components/ChatWorkspace.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/lib/assistant-ui-adapter.ts", import.meta.url), "utf8"),
  ]);

  assert.match(home, /<ChatWorkspace \/>/);
  assert.match(chat, /initialSessionId=\{sessionId\}/);
  assert.match(stats, /<StatsWorkspace \/>/);
  assert.match(models, /deepseek-v4-flash/);
  assert.match(models, /qwen3\.7-flash/);
  assert.match(models, /qwen3\.7-plus/);
  assert.match(models, /qwen3\.8-max/);
  assert.match(chatRoute, /proxyAgent/);
  assert.match(statsRoute, /proxyAgent/);
  assert.match(workspace, /双高问数/);
  assert.match(workspace, /onWorkflowSelect\("database-qa"\)/);
  assert.match(workspace, /onWorkflowSelect=\{selectWorkflow\}/);
  assert.match(workspace, /退出双高问数模式/);
  assert.match(workspace, /onWorkflowClear=\{\(\) => void resetChat\(\)\}/);
  assert.doesNotMatch(workspace, /rail-workflow-button/);
  assert.match(workspace, /workflowName: selectedWorkflowName/);
  assert.match(workspace, /scribe-workflow:/);
  assert.match(adapter, /workflow_name: config\.workflowName/);
});
