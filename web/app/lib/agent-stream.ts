export type AgentEvent = {
  type: string;
  scope?: string;
  text?: string;
  message?: string;
  label?: string;
  detail?: string;
  name?: string;
  input?: string;
  id?: string;
  seconds?: number;
  isError?: boolean;
  subagentType?: string;
  description?: string;
  tools?: number;
  skills?: string[];
  agents?: string[];
  commands?: string[];
  permissionMode?: string;
  inputTokens?: number;
  outputTokens?: number;
  costUsd?: number;
};

/** 解析一个 SSE data 帧；兼容 LF/CRLF，并忽略注释和空帧。 */
export function parseSseFrame(frame: string): AgentEvent | null {
  const line = frame
    .split(/\r?\n/)
    .find((part) => part.startsWith("data: "));
  if (!line) return null;
  return JSON.parse(line.slice(6)) as AgentEvent;
}

export async function readAgentStream(
  response: Response,
  onEvent: (event: AgentEvent) => void,
) {
  if (!response.body) throw new Error("响应没有数据流");
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  for (;;) {
    const { value, done } = await reader.read();
    buffer += decoder.decode(value, { stream: !done });
    const frames = buffer.split(/\r?\n\r?\n/);
    buffer = done ? "" : frames.pop() || "";
    for (const frame of frames) {
      const event = parseSseFrame(frame);
      if (event) onEvent(event);
    }
    if (done) break;
  }

  // 流结束时服务端可能没有再补一个空行，不能丢掉最后的 data 帧。
  const finalEvent = parseSseFrame(buffer);
  if (finalEvent) onEvent(finalEvent);
}
