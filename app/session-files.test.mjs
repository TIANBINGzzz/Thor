import { test } from "node:test";
import assert from "node:assert/strict";
import { Readable } from "node:stream";
import { readFile, writeFile } from "node:fs/promises";
import { join } from "node:path";
import {
  appendSessionTurn,
  cleanupSession,
  createSession,
  decodeFileId,
  listSessions,
  listSessionFiles,
  parseUpload,
  resolveSessionFile,
  sessionStats,
  sessionDirectory,
  sessionPromptContext,
  webSession,
} from "./session-files.mjs";

const BOUNDARY = "----ScribeTestBoundary";

/** 造一个真实的 multipart 请求流，filename 按 UTF-8 字节写入。 */
function uploadRequest(files) {
  const parts = [];

  for (const [filename, content] of files) {
    parts.push(
      Buffer.from(
        `--${BOUNDARY}\r\n` +
          `Content-Disposition: form-data; name="files"; filename="${filename}"\r\n` +
          "Content-Type: text/plain\r\n\r\n",
        "utf8",
      ),
      Buffer.from(content, "utf8"),
      Buffer.from("\r\n", "utf8"),
    );
  }

  parts.push(Buffer.from(`--${BOUNDARY}--\r\n`, "utf8"));

  const request = Readable.from([Buffer.concat(parts)]);
  request.headers = {
    "content-type": `multipart/form-data; boundary=${BOUNDARY}`,
  };
  return request;
}

test("中文文件名按 UTF-8 解码，不产生乱码", async (t) => {
  const { appSessionId } = await createSession();
  t.after(() => cleanupSession(appSessionId));

  const result = await parseUpload(
    uploadRequest([["季度经营分析 报告-v2.md", "# 标题\n\n正文"]]),
    appSessionId,
  );

  assert.equal(result.files.length, 1);
  assert.equal(result.files[0].originalName, "季度经营分析 报告-v2.md");
  assert.equal(result.files[0].source, "upload");
});

test("模型写进会话目录的文件会出现在清单里", async (t) => {
  const { appSessionId } = await createSession();
  t.after(() => cleanupSession(appSessionId));

  assert.deepEqual((await listSessionFiles(appSessionId)).files, []);

  // 模拟模型用 Write 工具把报告写进会话目录：内存里没有这条记录，
  // 只有读目录才能发现。
  await writeFile(
    join(sessionDirectory(appSessionId), "经营分析报告.md"),
    "# 报告\n",
    "utf8",
  );

  const { files } = await listSessionFiles(appSessionId);
  assert.equal(files.length, 1);
  assert.equal(files[0].originalName, "经营分析报告.md");
  assert.equal(files[0].source, "generated");
  assert.match(files[0].mimeType, /^text\/markdown/);
});

test("没有上传文件时也告知会话目录，避免产物写到项目根", async (t) => {
  const { appSessionId } = await createSession();
  t.after(() => cleanupSession(appSessionId));

  const context = await sessionPromptContext(appSessionId);
  assert.match(context, /当前会话没有上传文件/);
  assert.ok(context.includes(sessionDirectory(appSessionId)));
  assert.match(context, /必须写在该目录内/);
});

test("不存在的文件名解析失败", async (t) => {
  const { appSessionId } = await createSession();
  t.after(() => cleanupSession(appSessionId));

  await assert.rejects(
    () => resolveSessionFile(appSessionId, "missing.md"),
    /文件不存在/,
  );
});

test("下载解析拒绝越界路径，并保留原始文件名", async (t) => {
  const { appSessionId } = await createSession();
  t.after(() => cleanupSession(appSessionId));

  await parseUpload(
    uploadRequest([["数据口径说明.txt", "口径"]]),
    appSessionId,
  );
  const { files } = await listSessionFiles(appSessionId);

  const file = await resolveSessionFile(appSessionId, files[0].name);
  assert.equal(file.downloadName, "数据口径说明.txt");
  assert.equal(await readFile(file.path, "utf8"), "口径");

  await assert.rejects(
    () => resolveSessionFile(appSessionId, "../../package.json"),
    /文件不存在|不在会话目录内/,
  );
});

test("远程 Web 所需的会话、消息、事件和文件使用同一份本地状态", async (t) => {
  const created = await createSession({ model: "test-model" });
  t.after(() => cleanupSession(created.appSessionId));

  await parseUpload(
    uploadRequest([["输入资料.md", "# 数据"]]),
    created.appSessionId,
  );
  await appendSessionTurn(created.appSessionId, {
    prompt: "生成摘要",
    model: "test-model",
    agentSessionId: "agent-session",
    events: [
      { type: "init", tools: 3, skills: ["report-writing"], agents: [] },
      { type: "text", scope: "main", text: "摘要完成" },
      { type: "result", inputTokens: 10, outputTokens: 5, costUsd: 0.01 },
    ],
  });

  const data = await webSession(created.appSessionId);
  assert.equal(data.session.title, "生成摘要");
  assert.equal(data.messages[0].role, "user");
  assert.equal(data.messages[1].content, "摘要完成");
  assert.equal(data.messages[1].tokens, 15);
  assert.equal(data.files[0].name, "输入资料.md");
  assert.deepEqual(decodeFileId(data.files[0].id), {
    sessionId: created.appSessionId,
    name: (await listSessionFiles(created.appSessionId)).files[0].name,
  });

  const listed = await listSessions();
  assert.ok(listed.some((session) => session.id === created.appSessionId));
  const stats = await sessionStats();
  const model = stats.models.find((item) => item.modelId === "test-model");
  assert.equal(model?.responses, 1);
  assert.equal(model?.tokens, 15);
});
