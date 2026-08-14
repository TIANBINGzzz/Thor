import assert from "node:assert/strict";
import { test } from "node:test";
import { createTranslator } from "./sse-events.mjs";

function collect(messages) {
  const translate = createTranslator();
  const events = [];

  for (const message of messages) {
    events.push(...translate(message));
  }

  return events;
}

function streamStart(id, parent = null) {
  return {
    type: "stream_event",
    parent_tool_use_id: parent,
    event: { type: "message_start", message: { id, content: [] } },
  };
}

function streamText(text, parent = null) {
  return {
    type: "stream_event",
    parent_tool_use_id: parent,
    event: {
      type: "content_block_delta",
      delta: { type: "text_delta", text },
    },
  };
}

test("流式文本不与 assistant 文本块重复", () => {
  const events = collect([
    streamStart("msg_1"),
    streamText("你"),
    streamText("好"),
    {
      type: "assistant",
      parent_tool_use_id: null,
      message: { id: "msg_1", content: [{ type: "text", text: "你好" }] },
    },
  ]);

  const text = events
    .filter((event) => event.type === "text")
    .map((event) => event.text)
    .join("");

  assert.equal(text, "你好");
});

test("未经流式通道的 assistant 文本仍会输出", () => {
  const events = collect([
    {
      type: "assistant",
      parent_tool_use_id: null,
      message: { id: "msg_2", content: [{ type: "text", text: "直接输出" }] },
    },
  ]);

  assert.deepEqual(
    events.map((event) => event.text),
    ["直接输出"],
  );
});

test("子代理输出带独立 scope 和身份", () => {
  const events = collect([
    streamStart("msg_3", "tool_1"),
    streamText("子代理正文", "tool_1"),
    {
      type: "assistant",
      parent_tool_use_id: "tool_1",
      subagent_type: "writer",
      task_description: "撰写报告",
      message: { id: "msg_3", content: [] },
    },
  ]);

  const text = events.find((event) => event.type === "text");
  assert.equal(text.scope, "sub:tool_1");

  const subagent = events.find((event) => event.type === "subagent");
  assert.equal(subagent.subagentType, "writer");
  assert.equal(subagent.description, "撰写报告");
});

test("工具调用与结果按 id 配对", () => {
  const events = collect([
    {
      type: "assistant",
      parent_tool_use_id: null,
      message: {
        id: "msg_4",
        content: [
          { type: "tool_use", id: "t1", name: "Read", input: { file: "a.md" } },
        ],
      },
    },
    {
      type: "user",
      parent_tool_use_id: null,
      message: {
        content: [
          { type: "tool_result", tool_use_id: "t1", content: "文件内容" },
        ],
      },
    },
  ]);

  const use = events.find((event) => event.type === "tool_use");
  assert.equal(use.name, "Read");
  assert.equal(use.id, "t1");

  const result = events.find((event) => event.type === "tool_result");
  assert.equal(result.id, "t1");
  assert.equal(result.isError, false);
});

test("init 汇总能力清单", () => {
  const events = collect([
    {
      type: "system",
      subtype: "init",
      session_id: "s1",
      model: "qwen3.8-max",
      cwd: "D:\\x",
      permissionMode: "bypassPermissions",
      tools: ["Read", "Write"],
      skills: ["report-writing"],
      agents: ["writer"],
      slash_commands: ["report"],
      mcp_servers: [{ name: "db", status: "connected" }],
    },
  ]);

  assert.equal(events[0].type, "init");
  assert.equal(events[0].tools, 2);
  assert.deepEqual(events[0].skills, ["report-writing"]);
});

test("subtype 为 success 但 is_error 时仍报告错误", () => {
  const events = collect([
    {
      type: "result",
      subtype: "success",
      is_error: true,
      result: "认证失败",
      session_id: "s1",
      duration_ms: 700,
      num_turns: 1,
      total_cost_usd: 0,
      modelUsage: {},
    },
  ]);

  assert.equal(events[0].ok, false);
  assert.equal(events[0].message, "认证失败");
});

test("未识别的消息类型降级为 activity 而不是丢弃", () => {
  const events = collect([
    { type: "some_future_message", parent_tool_use_id: null, subtype: "x" },
  ]);

  assert.equal(events[0].type, "activity");
  assert.equal(events[0].label, "some_future_message");
});

test("status 心跳不进 UI", () => {
  const events = collect([
    { type: "system", subtype: "status", parent_tool_use_id: null },
  ]);

  assert.equal(events.length, 0);
});

// 这些噪声全是 type: "system" 下的 subtype。曾经按顶层 type 过滤，
// 结果一次对话刷出上百条 thinking_tokens。
test("高频计量类 system 消息按 subtype 过滤", () => {
  const noisy = [
    "thinking_tokens",
    "session_state_changed",
    "background_tasks_changed",
    "commands_changed",
    "files_persisted",
  ].map((subtype) => ({ type: "system", subtype, parent_tool_use_id: null }));

  assert.equal(collect(noisy).length, 0);
});

test("未列入噪声的 system 消息仍然可见", () => {
  const events = collect([
    { type: "system", subtype: "mcp_server_failed", parent_tool_use_id: null },
  ]);

  assert.deepEqual(events, [
    { type: "activity", scope: "main", label: "system/mcp_server_failed", detail: "" },
  ]);
});
