import dotenv from "dotenv";
import { createDatabaseMcpServer } from "./database.mjs";

// override 是必需的：cc-switch 等供应商切换工具会往系统环境注入
// ANTHROPIC_BASE_URL，dotenv 默认不覆盖已存在的变量，会导致 .env 里的
// 地址被静默忽略，把 Qwen key 发到别人的网关上。
// 本项目约定密钥和连接只放 .env，因此 .env 是权威源。
dotenv.config({ override: true, quiet: true });

const REQUIRED_VARIABLES = [
  "ANTHROPIC_AUTH_TOKEN",
  "ANTHROPIC_BASE_URL",
  "ANTHROPIC_MODEL",
];

const DATABASE_APPEND =
  "涉及数据库事实时必须使用 db MCP 工具，先检查结构，再执行必要的 SQL，并基于真实结果回答。默认只读；除非用户明确授权，不执行写入或结构变更。";

const BASE_APPEND =
  "遵循项目 CLAUDE.md 和已加载的项目 Skills；没有可靠证据时明确说明不确定性。";

// harness 的系统提示是英文，模型会跟着用英文思考和回话。这里显式要求中文，
// 并把范围写到思考、进度和待办上，否则只有最终答复是中文。
const LANGUAGE_APPEND =
  "始终使用简体中文回答，包括思考过程、进度说明、工具调用前的说明、待办事项和最终报告。" +
  "代码、标识符、命令、文件路径、日志原文和引用的英文原文保持原样，不要翻译。" +
  "即使用户使用英文提问，也用简体中文回答。";

// WebSearch 在当前 Qwen 兼容网关上不真正执行搜索，却返回 isError: false，
// 属于伪造成功，比干净报错更容易让模型把编造内容当搜索结果写进报告。
// WebFetch 不同：它由 CLI 在本机直接发请求，不经过网关，配好 .env 里的
// 代理后可用。但"能抓取"不等于"能搜索"——没有搜索就没法发现 URL，
// 编 URL 正是此前 WebFetch 报 404 的真实原因。
const NO_WEB_APPEND =
  "当前运行环境没有可用的联网搜索能力：WebSearch 不可用，不要调用，也不要把它的返回当作搜索结果。" +
  "WebFetch 可用，但只能抓取已经确切知道的 URL，不能用来搜索或发现网页。" +
  "禁止猜测或拼凑 URL 去试——编造的链接会返回 404，把它当成已核实是错的。" +
  "需要外部时效性事实时，用 WebFetch 抓取用户提供的确切链接，或用命令行工具（例如 npm view、curl）取真实数据，" +
  "否则明确说明该事实未经联网核实。禁止编造搜索结果、链接、引用或访问日期。";

const DISALLOWED_TOOLS = ["WebSearch"];

/** 返回缺失或仍是占位值的环境变量名。 */
export function missingEnvironment() {
  return REQUIRED_VARIABLES.filter((name) => {
    const value = process.env[name];
    return !value || value.includes("YOUR_");
  });
}

/**
 * 构造 query() 的 options。CLI 入口和 HTTP 服务共用同一套配置，
 * 避免两处行为漂移。
 */
export function buildAgentOptions({
  maxTurns = 10,
  resume,
  model,
  includePartialMessages = false,
  abortController,
  additionalDirectories = [],
} = {}) {
  const databaseServer = createDatabaseMcpServer();
  const databaseEnabled = databaseServer !== null;

  return {
    maxTurns,
    model: model || process.env.ANTHROPIC_MODEL,
    settingSources: ["project", "local"],
    tools: {
      type: "preset",
      preset: "claude_code",
    },
    systemPrompt: {
      type: "preset",
      preset: "claude_code",
      append: [
        databaseEnabled ? DATABASE_APPEND : BASE_APPEND,
        LANGUAGE_APPEND,
        NO_WEB_APPEND,
      ].join("\n\n"),
    },
    disallowedTools: DISALLOWED_TOOLS,
    permissionMode: "bypassPermissions",
    allowDangerouslySkipPermissions: true,
    env: { ...process.env },
    ...(resume ? { resume } : {}),
    ...(includePartialMessages ? { includePartialMessages: true } : {}),
    ...(abortController ? { abortController } : {}),
    ...(additionalDirectories.length > 0 ? { additionalDirectories } : {}),
    ...(databaseEnabled
      ? {
          mcpServers: { db: databaseServer },
          allowedTools: ["mcp__db__*"],
        }
      : {}),
  };
}
