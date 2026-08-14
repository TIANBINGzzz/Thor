import "dotenv/config";

import { query, type Options, type SDKMessage } from "@anthropic-ai/claude-agent-sdk";

const COMMON_TOOLS = [
  "Read",
  "Write",
  "Edit",
  "Glob",
  "Grep",
  "Bash",
  "WebSearch",
  "WebFetch",
  "NotebookEdit",
  "TodoWrite",
  "Task",
  "Agent",
] as const;

function requiredEnv(name: string): string {
  const value = process.env[name]?.trim();
  if (!value) {
    throw new Error(`Missing ${name}. Add it to .env (see .env.example).`);
  }
  return value;
}

function textFromAssistant(message: SDKMessage): string[] {
  if (message.type !== "assistant") return [];

  return message.message.content.flatMap((block) => {
    if (block.type === "text") return [block.text];
    if (block.type === "tool_use") return [`[tool] ${block.name}`];
    return [];
  });
}

async function run(prompt: string, checkOnly: boolean): Promise<void> {
  const baseUrl = requiredEnv("ANTHROPIC_BASE_URL");
  requiredEnv("ANTHROPIC_AUTH_TOKEN");
  const model = requiredEnv("ANTHROPIC_MODEL");

  const options: Options = {
    cwd: process.cwd(),
    model,
    env: {
      ...process.env,
      ANTHROPIC_BASE_URL: baseUrl,
      ANTHROPIC_MODEL: model,
      CLAUDE_AGENT_SDK_CLIENT_APP: "thor/1.0.0",
      CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC: "1",
    },
    maxTurns: checkOnly ? 1 : 30,
    tools: checkOnly ? [] : { type: "preset", preset: "claude_code" },
    allowedTools: checkOnly ? [] : [...COMMON_TOOLS],
    skills: checkOnly ? [] : "all",
    settingSources: ["user", "project", "local"],
    permissionMode: "dontAsk",
  };

  let finalResult: SDKMessage | undefined;

  for await (const message of query({ prompt, options })) {
    for (const text of textFromAssistant(message)) {
      process.stdout.write(`${text}\n`);
    }
    if (message.type === "result") finalResult = message;
  }

  if (!finalResult || finalResult.type !== "result") {
    throw new Error("The agent ended without returning a result.");
  }
  if (finalResult.subtype !== "success") {
    throw new Error(finalResult.errors.join("\n") || `Agent failed: ${finalResult.subtype}`);
  }

  if (checkOnly) {
    console.log(`Connection OK: ${model} via ${new URL(baseUrl).origin}`);
  }
}

async function main(): Promise<void> {
  const args = process.argv.slice(2);
  const checkOnly = args[0] === "--check";
  const prompt = checkOnly
    ? "Reply with exactly: CONNECTION_OK"
    : args.join(" ").trim();

  if (!prompt) {
    console.error('Usage: npm run agent -- "your task"');
    process.exitCode = 2;
    return;
  }

  await run(prompt, checkOnly);
}

main().catch((error: unknown) => {
  const message = error instanceof Error ? error.message : String(error);
  console.error(`Error: ${message}`);
  process.exitCode = 1;
});
