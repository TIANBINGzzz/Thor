import { buildAgentOptions, missingEnvironment } from "./agent-options.mjs";
import { runPythonAgent } from "./python-agent.mjs";

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
  let agentError;
  await runPythonAgent({
    prompt,
    model: options.model,
    max_turns: options.maxTurns,
    mcp_servers: options.mcpServers,
    allowed_tools: options.allowedTools,
    system_prompt_append: options.systemPrompt?.append || "",
  }, {
    onEvent: (event) => {
      if (event.type === "text" && (!event.scope || event.scope === "main")) {
        process.stdout.write(`${event.text}\n`);
      }
      if (event.type === "error") agentError = event.message || "调用失败";
    },
  });
  if (agentError) throw new Error(agentError);
} catch (error) {
  console.error(error instanceof Error ? error.message : error);
  process.exitCode = 1;
}
