import { test } from "node:test";
import assert from "node:assert/strict";
import { Readable } from "node:stream";
import { readFile, writeFile } from "node:fs/promises";
import { join } from "node:path";
import {
  appendSessionTurn,
  upsertSessionTurn,
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
  assert.equal(result.uploaded.length, 1);
  assert.equal(result.uploaded[0], result.files[0].name);
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

test("模型生成的文件也会进入后续对话上下文", async (t) => {
  const { appSessionId } = await createSession();
  t.after(() => cleanupSession(appSessionId));

  await writeFile(
    join(sessionDirectory(appSessionId), "后续报告.md"),
    "# 报告\n",
    "utf8",
  );

  const context = await sessionPromptContext(appSessionId);
  assert.match(context, /后续报告\.md/);
  assert.match(context, /模型生成/);
});

test("没有上传文件时也告知会话目录，避免产物写到项目根", async (t) => {
  const { appSessionId } = await createSession();
  t.after(() => cleanupSession(appSessionId));

  const context = await sessionPromptContext(appSessionId);
  assert.match(context, /当前会话没有文件/);
  assert.ok(context.includes(sessionDirectory(appSessionId)));
  assert.match(context, /必须写在该目录内/);
  assert.match(context, /最终交付物必须是有效且可打开的 \.docx 文件/);
});

test("流式会话更新同一个 turn，刷新时保留用户消息和已收到事件", async (t) => {
  const { appSessionId } = await createSession({ model: "test-model" });
  t.after(() => cleanupSession(appSessionId));

  await upsertSessionTurn(appSessionId, {
    turnId: "stream-turn",
    prompt: "处理这个文档",
    model: "test-model",
    events: [],
  });
  await upsertSessionTurn(appSessionId, {
    turnId: "stream-turn",
    prompt: "处理这个文档",
    model: "test-model",
    agentSessionId: "agent-session",
    events: [
      { type: "thinking", text: "读取文件" },
      { type: "text", scope: "main", text: "处理中" },
    ],
  });

  const data = await webSession(appSessionId);
  assert.equal(data.messages.length, 2);
  assert.equal(data.messages[0].content, "处理这个文档");
  assert.equal(data.messages[1].content, "处理中");
  assert.equal(data.session.agentSessionId, "agent-session");
});

test("生成文件只挂到产生它的 assistant turn", async (t) => {
  const created = await createSession({ model: "test-model" });
  t.after(() => cleanupSession(created.appSessionId));

  const firstFile = join(sessionDirectory(created.appSessionId), "第一轮.docx");
  const secondFile = join(sessionDirectory(created.appSessionId), "第二轮.docx");
  await writeFile(firstFile, "first", "utf8");
  await appendSessionTurn(created.appSessionId, {
    turnId: "turn-one",
    prompt: "生成第一份文件",
    model: "test-model",
    events: [{ type: "text", scope: "main", text: "第一轮完成" }],
    files: ["第一轮.docx"],
  });
  await writeFile(secondFile, "second", "utf8");
  await appendSessionTurn(created.appSessionId, {
    turnId: "turn-two",
    prompt: "生成第二份文件",
    model: "test-model",
    events: [{ type: "text", scope: "main", text: "第二轮完成" }],
    files: ["第二轮.docx"],
  });

  const data = await webSession(created.appSessionId);
  assert.deepEqual(data.messages[1].files.map((file) => file.name), ["第一轮.docx"]);
  assert.deepEqual(data.messages[3].files.map((file) => file.name), ["第二轮.docx"]);
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
