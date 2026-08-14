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
    const frames = buffer.split("\n\n");
    buffer = frames.pop() || "";
    for (const frame of frames) {
      const line = frame.split("\n").find((part) => part.startsWith("data: "));
      if (line) onEvent(JSON.parse(line.slice(6)) as AgentEvent);
    }
    if (done) break;
  }
}
