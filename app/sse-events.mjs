/**
 * 把 Claude Agent SDK 的消息流翻译成一套紧凑的 UI 事件。
 *
 * 设计取舍：SDK 的 SDKMessage 是 40+ 种类型的联合。这里不做白名单，
 * 未识别的类型统一降级成 activity 事件，保证新增消息类型不会被静默丢弃。
 *
 * 文本只从 stream_event 的增量取，assistant 消息里的 text 块跳过，
 * 否则同一段话会渲染两次。
 */

const TEXT_LIMIT = 2000;

/** 子代理消息带非空 parent_tool_use_id，据此和主线程输出分流。 */
function scopeOf(message) {
  return message.parent_tool_use_id ? `sub:${message.parent_tool_use_id}` : "main";
}

function clip(value) {
  if (value === undefined || value === null) {
    return "";
  }

  const text = typeof value === "string" ? value : JSON.stringify(value);

  if (typeof text !== "string") {
    return "";
  }

  return text.length > TEXT_LIMIT ? `${text.slice(0, TEXT_LIMIT)}…` : text;
}

function* fromStreamEvent(message, streaming) {
  const event = message.event;
  const scope = scopeOf(message);

  if (event.type === "message_start") {
    // 记下正在走增量通道的 message id，稍后跳过它的 text 块。
    streaming.set(scope, event.message.id);
    return;
  }

  if (event.type === "message_stop") {
    streaming.delete(scope);
    return;
  }

  if (event.type === "content_block_delta") {
    const delta = event.delta;

    if (delta.type === "text_delta" && delta.text) {
      yield { type: "text", scope, text: delta.text };
    }

    if (delta.type === "thinking_delta" && delta.thinking) {
      yield { type: "thinking", scope, text: delta.thinking };
    }
  }
}

function* fromAssistant(message, streaming) {
  const scope = scopeOf(message);
  const inner = message.message;
  // 一次 turn 可能产生多条共用同一 message.id 的 assistant 消息
  // （thinking 一条、text 一条）。因此这里只比对、不消费标记，
  // 标记由 message_stop 清除，否则第二条的 text 会重复输出。
  const alreadyStreamed = streaming.get(scope) === inner.id;

  if (message.subagent_type) {
    yield {
      type: "subagent",
      scope,
      subagentType: message.subagent_type,
      description: message.task_description || "",
    };
  }

  for (const block of inner.content || []) {
    if (block.type === "text" && block.text && !alreadyStreamed) {
      yield { type: "text", scope, text: block.text };
    }

    if (block.type === "tool_use") {
      yield {
        type: "tool_use",
        scope,
        id: block.id,
        name: block.name,
        input: clip(block.input),
      };
    }
  }
}

function* fromUser(message) {
  const scope = scopeOf(message);
  const content = message.message?.content;

  if (!Array.isArray(content)) {
    return;
  }

  for (const block of content) {
    if (block.type === "tool_result") {
      yield {
        type: "tool_result",
        scope,
        id: block.tool_use_id,
        isError: block.is_error === true,
        text: clip(block.content),
      };
    }
  }
}

function* fromSystem(message) {
  const scope = scopeOf(message);

  if (message.subtype === "init") {
    yield {
      type: "init",
      sessionId: message.session_id,
      model: message.model,
      cwd: message.cwd,
      permissionMode: message.permissionMode,
      tools: message.tools?.length || 0,
      skills: message.skills || [],
      agents: message.agents || [],
      commands: message.slash_commands || [],
      mcpServers: message.mcp_servers || [],
    };
    return;
  }

  if (message.subtype === "task_started") {
    yield {
      type: "activity",
      scope,
      label: message.subagent_type
        ? `子代理启动 ${message.subagent_type}`
        : `任务启动 ${message.task_type || ""}`.trim(),
      detail: message.description || message.workflow_name || "",
    };
    return;
  }

  if (message.subtype === "compact_boundary") {
    yield { type: "activity", scope, label: "上下文压缩", detail: "" };
    return;
  }

  if (NOISE.has(message.subtype)) {
    return;
  }

  yield { type: "activity", scope, label: `system/${message.subtype}`, detail: "" };
}

function* fromResult(message) {
  const usage = Object.values(message.modelUsage || {}).reduce(
    (total, entry) => ({
      input: total.input + (entry.inputTokens || 0),
      output: total.output + (entry.outputTokens || 0),
    }),
    { input: 0, output: 0 },
  );

  yield {
    type: "result",
    ok: message.subtype === "success" && !message.is_error,
    subtype: message.subtype,
    sessionId: message.session_id,
    durationMs: message.duration_ms,
    turns: message.num_turns,
    costUsd: message.total_cost_usd,
    inputTokens: usage.input,
    outputTokens: usage.output,
    // is_error 可以在 subtype 仍是 success 时为真，此时错误内容只在 result 字段里。
    message:
      message.subtype === "success" && !message.is_error
        ? ""
        : message.errors?.join("; ") ||
          message.result ||
          `执行结束：${message.subtype}`,
  };
}

/**
 * 高频计量/心跳类消息的 subtype，逐条渲染会淹没界面，直接丢弃。
 * 这些全部是 type: "system" 下的 subtype，不是顶层 type。
 * 有价值的等价信息已经在 result 的 token 统计里。
 */
const NOISE = new Set([
  "status",
  "thinking_tokens",
  "session_state_changed",
  "background_tasks_changed",
  "commands_changed",
  "files_persisted",
]);

/**
 * 每个请求建一个翻译器，内部维护文本去重状态。
 */
export function createTranslator() {
  /** scope -> 当前正在流式输出的 message.id */
  const streaming = new Map();

  return function* translate(message) {
    switch (message.type) {
      case "stream_event":
        yield* fromStreamEvent(message, streaming);
        return;
      case "assistant":
        yield* fromAssistant(message, streaming);
        return;
      case "user":
        yield* fromUser(message);
        return;
      case "system":
        yield* fromSystem(message);
        return;
      case "result":
        yield* fromResult(message);
        return;
      case "tool_progress":
        // 心跳频繁，交给前端按 tool_use_id 更新耗时即可。
        yield {
          type: "tool_progress",
          scope: scopeOf(message),
          id: message.tool_use_id,
          seconds: Math.round(message.elapsed_time_seconds || 0),
        };
        return;
      default:
        yield {
          type: "activity",
          scope: scopeOf(message),
          label: message.type,
          detail: message.subtype || "",
        };
    }
  };
}
