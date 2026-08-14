import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

async function render() {
  const workerUrl = new URL("../dist/server/index.js", import.meta.url);
  workerUrl.searchParams.set("test", `${process.pid}-${Date.now()}`);
  const { default: worker } = await import(workerUrl.href);

  return worker.fetch(
    new Request("http://localhost/", {
      headers: { accept: "text/html" },
    }),
    {
      ASSETS: {
        fetch: async () => new Response("Not found", { status: 404 }),
      },
    },
    {
      waitUntil() {},
      passThroughOnException() {},
    },
  );
}

test("server-renders the Luma chat shell", async () => {
  const response = await render();
  assert.equal(response.status, 200);
  assert.match(response.headers.get("content-type") ?? "", /^text\/html\b/i);

  const html = await response.text();
  assert.match(html, /<html lang="zh-CN">/);
  assert.match(html, /<title>Luma — 清晰地对话<\/title>/);
  assert.match(html, /历史会话/);
  assert.match(html, /deepseek-v4-flash/);
  assert.match(html, /文件最大 10 MB/);
  assert.doesNotMatch(html, /codex-preview|Building your site|Starter Project/i);
});

test("keeps the chat and statistics entry points", async () => {
  const [home, chat, stats, models] = await Promise.all([
    readFile(new URL("../app/page.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/chat/[sessionId]/page.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/stats/page.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/lib/models.ts", import.meta.url), "utf8"),
  ]);

  assert.match(home, /<ChatWorkspace \/>/);
  assert.match(chat, /initialSessionId=\{sessionId\}/);
  assert.match(stats, /<StatsWorkspace \/>/);
  assert.match(models, /deepseek-v4-flash/);
  assert.match(models, /qwen3\.8-max/);
});
