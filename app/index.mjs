import { query } from "@anthropic-ai/claude-agent-sdk";
import { buildAgentOptions, missingEnvironment } from "./agent-options.mjs";

const invalidVariables = missingEnvironment();

if (invalidVariables.length > 0) {
  console.error(
    `请先在项目根目录的 .env 中配置：${invalidVariables.join(", ")}`,
  );
  process.exit(1);
}

const prompt = process.argv.slice(2).join(" ") || "你好，请用一句话介绍你自己。";
const options = buildAgentOptions({ maxTurns: 10 });

try {
  for await (const message of query({ prompt, options })) {
    if (message.type === "assistant") {
      for (const block of message.message.content) {
        if (block.type === "text") {
          process.stdout.write(`${block.text}\n`);
        }
      }
    }

    if (message.type === "result" && message.subtype !== "success") {
      throw new Error(message.errors?.join("; ") || `调用失败：${message.subtype}`);
    }
  }
} catch (error) {
  console.error(error instanceof Error ? error.message : error);
  process.exitCode = 1;
}
