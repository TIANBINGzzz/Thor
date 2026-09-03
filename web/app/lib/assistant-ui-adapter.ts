import type {
  ChatModelAdapter,
  ChatModelRunOptions,
  ChatModelRunResult,
  ThreadAssistantMessagePart,
  ThreadMessageLike,
} from "@assistant-ui/react";
import { parseSseFrame, type AgentEvent } from "./agent-stream";

type AdapterConfig = {
  sessionId: string | null;
  modelId: string;
  clientId: string;
  workflowName?: string | null;
  onRunStart?: () => void;
  onEvent?: (event: AgentEvent) => void;
  onRunEnd?: () => void;
  onSessionCreated?: (sessionId: string) => void;
  onComplete?: (sessionId: string) => void | Promise<void>;
  onError?: (error: string) => void;
};

export type RunPhase = "idle" | "thinking" | "tool" | "reply";

export type PersistedMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  events?: AgentEvent[];
  files?: PersistedFile[];
  createdAt?: number;
};

export type PersistedFile = {
  id: string;
  sessionId: string;
  name: string;
  contentType: string;
  size: number;
  createdAt: number;
  source?: string;
  url: string;
};

type RuntimeEventResult = {
  kind: "activity" | "subagent" | "environment" | "error";
  label: string;
  detail?: string;
  isError?: boolean;
};

type RuntimeParts = {
  parts: ThreadAssistantMessagePart[];
  toolIndexes: Map<string, number>;
  toolArgs: Map<string, string>;
  toolProgress: Map<string, number>;
  lastThinkingScope: string | null;
  sequence: number;
};

const RUNTIME_TOOL_NAME = "__luma_runtime__";

export function isRuntimeEventResult(value: unknown): value is RuntimeEventResult {
  if (!value || typeof value !== "object") return false;
  return "kind" in value && "label" in value;
}

function runtimeTool(state: RuntimeParts, result: RuntimeEventResult) {
  state.sequence += 1;
  state.parts.push({
    type: "tool-call",
    toolCallId: `runtime-${state.sequence}`,
    toolName: RUNTIME_TOOL_NAME,
    args: {},
    argsText: "",
    result,
    isError: result.isError,
  });
  state.lastThinkingScope = null;
}

function applyEvent(state: RuntimeParts, event: AgentEvent) {
  if (event.type === "thinking") {
    const scope = event.scope || "main";
    const lastIndex = state.parts.length - 1;
    const last = state.parts[lastIndex];
    if (last?.type === "reasoning" && state.lastThinkingScope === scope) {
      state.parts[lastIndex] = { ...last, text: `${last.text}${event.text || ""}` };
    } else {
      state.parts.push({ type: "reasoning", text: event.text || "" });
    }
    state.lastThinkingScope = scope;
    return true;
  }

  if (event.type === "tool_use") {
    state.sequence += 1;
    const toolCallId = event.id || `tool-${state.sequence}`;
    state.toolIndexes.set(toolCallId, state.parts.length);
    state.toolArgs.set(toolCallId, event.input || "");
    state.parts.push({
      type: "tool-call",
      toolCallId,
      toolName: event.name || "工具调用",
      args: {},
      argsText: event.input || "",
    });
    state.lastThinkingScope = null;
    return true;
  }

  if (event.type === "tool_result") {
    const index = event.id ? state.toolIndexes.get(event.id) : undefined;
    if (index !== undefined) {
      const part = state.parts[index];
      if (part?.type === "tool-call") {
        state.parts[index] = {
          ...part,
          argsText: state.toolArgs.get(event.id || "") || part.argsText,
          result: event.text || (event.isError ? "工具执行失败" : "工具执行完成"),
          isError: event.isError,
        };
      }
    } else {
      state.sequence += 1;
      state.parts.push({
        type: "tool-call",
        toolCallId: event.id || `tool-result-${state.sequence}`,
        toolName: "工具结果",
        args: {},
        argsText: "",
        result: event.text || (event.isError ? "工具执行失败" : "工具执行完成"),
        isError: event.isError,
      });
    }
    if (event.id) {
      state.toolProgress.delete(event.id);
      state.toolArgs.delete(event.id);
    }
    state.lastThinkingScope = null;
    return true;
  }

  if (event.type === "tool_progress") {
    const toolId = event.id;
    if (!toolId) return false;
    const index = state.toolIndexes.get(toolId);
    if (index !== undefined) {
      const part = state.parts[index];
      const seconds = Number(event.seconds || 0);
      if (part?.type === "tool-call" && state.toolProgress.get(toolId) !== seconds) {
        const baseArgs = state.toolArgs.get(toolId) || part.argsText || "";
        state.toolProgress.set(toolId, seconds);
        state.parts[index] = {
          ...part,
          argsText: `${baseArgs}${baseArgs ? "\n\n" : ""}运行中 · ${seconds} 秒`,
        };
        return true;
      }
    }
    return false;
  }

  if (event.type === "subagent") {
    runtimeTool(state, {
      kind: "subagent",
      label: event.subagentType || "子代理",
      detail: event.description,
    });
    return true;
  }

  if (event.type === "init") {
    runtimeTool(state, {
      kind: "environment",
      label: `${event.tools || 0} 工具 · ${event.skills?.length || 0} Skills · ${event.agents?.length || 0} 子代理`,
    });
    return true;
  }

  if (event.type === "activity") {
    runtimeTool(state, {
      kind: "activity",
      label: event.label || "运行动态",
      detail: event.detail,
    });
    return true;
  }

  if (event.type === "error") {
    runtimeTool(state, {
      kind: "error",
      label: event.message || "运行失败",
      isError: true,
    });
    return true;
  }

  return false;
}

function createRuntimeParts(events: AgentEvent[] = []) {
  const state: RuntimeParts = {
    parts: [],
    toolIndexes: new Map(),
    toolArgs: new Map(),
    toolProgress: new Map(),
    lastThinkingScope: null,
    sequence: 0,
  };
  for (const event of events) applyEvent(state, event);
  return state;
}

function contentSnapshot(runtimeParts: ThreadAssistantMessagePart[], text: string) {
  const content = [...runtimeParts];
  if (text) content.push({ type: "text", text });
  return content;
}

export function persistedMessagesToThreadMessages(messages: PersistedMessage[]): ThreadMessageLike[] {
  return messages.map((message) => ({
    id: message.id,
    role: message.role,
    content: message.role === "assistant"
      ? contentSnapshot(createRuntimeParts(message.events).parts, message.content)
      : message.content,
    createdAt: message.createdAt ? new Date(message.createdAt) : undefined,
    status: message.role === "assistant" ? { type: "complete", reason: "stop" } : undefined,
  }));
}

export function isRuntimeToolName(toolName: string) {
  return toolName === RUNTIME_TOOL_NAME;
}

export function createChatModelAdapter(config: AdapterConfig): ChatModelAdapter {
  return {
    async *run(options: ChatModelRunOptions): AsyncGenerator<ChatModelRunResult, void> {
      const lastMessage = options.messages.at(-1);
      if (!lastMessage || lastMessage.role !== "user") return;

      const prompt = lastMessage.content
        .filter((part): part is { type: "text"; text: string } => part.type === "text")
        .map((part) => part.text)
        .join("");

      if (!prompt.trim()) return;

      config.onRunStart?.();
      let runEnded = false;
      const endRun = () => {
        if (runEnded) return;
        runEnded = true;
        config.onRunEnd?.();
      };

      let activeSessionId = config.sessionId;
      if (!activeSessionId) {
        try {
          const response = await fetch("/api/sessions", {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              "x-luma-client-id": config.clientId,
            },
            body: JSON.stringify({ modelId: config.modelId }),
          });
          if (!response.ok) throw new Error(`创建会话失败 (${response.status})`);
          const data = (await response.json()) as { session: { id: string } };
          activeSessionId = data.session.id;
          config.onSessionCreated?.(activeSessionId);
        } catch (error) {
          endRun();
          config.onError?.(error instanceof Error ? error.message : "创建会话失败");
          return;
        }
      }

      try {
        const response = await fetch(`/api/sessions/${activeSessionId}/chat`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "x-luma-client-id": config.clientId,
          },
          body: JSON.stringify({
            prompt,
            modelId: config.modelId,
            ...(config.workflowName ? { workflow_name: config.workflowName } : {}),
          }),
          signal: options.abortSignal,
        });

        if (!response.ok) {
          const detail = (await response.json().catch(() => ({}))) as { error?: string };
          throw new Error(detail.error || `请求失败 (${response.status})`);
        }
        if (!response.body) throw new Error("响应体为空");

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        const runtime = createRuntimeParts();
        let textContent = "";
        let buffer = "";

        const processFrame = (frame: string) => {
          const event = parseSseFrame(frame);
          if (!event) return;
          config.onEvent?.(event);

          let changed = false;
          if (event.type === "text" && (!event.scope || event.scope === "main")) {
            textContent += event.text || "";
            changed = true;
          } else {
            changed = applyEvent(runtime, event);
          }

          if (changed) {
            pendingResults.push({ content: contentSnapshot(runtime.parts, textContent) });
          }
        };
        const pendingResults: ChatModelRunResult[] = [];

        try {
          for (;;) {
            const { done, value } = await reader.read();
            buffer += decoder.decode(value, { stream: !done });
            const frames = buffer.split(/\r?\n\r?\n/);
            buffer = done ? "" : frames.pop() || "";

            for (const frame of frames) {
              processFrame(frame);
              while (pendingResults.length) yield pendingResults.shift()!;
            }
            if (done) break;
          }

          // 服务端正常结束时最后一帧不一定以空行结尾。
          processFrame(buffer);
          while (pendingResults.length) yield pendingResults.shift()!;
        } finally {
          reader.releaseLock();
        }

        yield {
          content: contentSnapshot(runtime.parts, textContent),
          status: { type: "complete", reason: "stop" },
        };
        await config.onComplete?.(activeSessionId);
      } catch (error) {
        if (!(error instanceof DOMException && error.name === "AbortError")) {
          config.onError?.(error instanceof Error ? error.message : "发送失败");
        }
      } finally {
        endRun();
      }
    },
  };
}
