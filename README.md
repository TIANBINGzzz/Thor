# Thor / CCSDKScribe

一个基于 Claude Agent SDK 的本地 Node.js Agent 与对话应用。项目通过 Anthropic 兼容接口调用 Qwen，加载 Claude Code 的工具、项目指令、Skills、Subagents 和 Commands，并通过 MCP 接入数据库。`web/` 是唯一前端，保留远程 Thor 的 Luma 组件、样式和布局，并接入本地 Agent 全部运行时能力。

## CC SDK 是什么语言

Claude Code SDK 现名 Claude Agent SDK，官方提供 TypeScript/JavaScript 和 Python 两套 SDK。本项目选用 JavaScript 版本，因此没有 Python 文件也完全正常。

`.mjs` 是 Node.js 的 ECMAScript Module 文件扩展名，使用 `import` / `export`，相对于传统 CommonJS 的 `.cjs` / `require()`。本项目的 `package.json` 也设置了 `"type": "module"`；继续使用 `.mjs` 是为了让模块类型一眼可见。

Python 常见于数据科学、Notebook 和某些 workflow 框架，但 workflow 编排并不依赖 Python。Claude Agent SDK 可以直接在 Node.js 中完成模型调用、工具编排、MCP、会话和多代理控制。只有需要 pandas、PyTorch 或 Python 专属服务时，才有必要增加 Python 子服务。

## 项目结构

```text
CCSDKScribe/
├── CLAUDE.md                         # 项目级长期指令
├── .claude/
│   ├── settings.json                 # 可共享的项目配置
│   ├── settings.local.json           # 本机覆盖配置，不提交 Git
│   ├── launch.json                    # 前端调试用的开发服务定义
│   ├── skills/
│   │   ├── data-analysis/SKILL.md     # 数据分析流程
│   │   ├── rag-answer/SKILL.md        # 检索增强问答流程
│   │   ├── report-writing/SKILL.md    # 专业报告流程
│   │   ├── flux-ui/                   # 远程 UI 设计规范
│   │   ├── project-conventions/       # 项目约定
│   │   └── ui/                        # UI 设计资源与 recipes
│   ├── agents/
│   │   ├── researcher.md              # 研究员子代理
│   │   ├── data-analyst.md            # 数据分析子代理
│   │   └── writer.md                  # 报告撰稿子代理
│   ├── workflows/
│   │   └── professional-report.js      # 三阶段动态报告编排
│   └── commands/
│       └── report.md                  # /report 命令
├── .mcp.json                          # 项目级静态 MCP 配置入口
├── app/
│   ├── index.mjs                      # CLI 入口
│   ├── agent-options.mjs              # CLI 与 HTTP 共用的 query() 配置
│   ├── server.mjs                     # 本机 HTTP + SSE 服务
│   ├── sse-events.mjs                 # SDK 消息流 → UI 事件翻译层
│   ├── sse-events.test.mjs            # 翻译层单元测试
│   ├── session-files.mjs              # 应用会话目录与上传/产物文件
│   ├── session-files.test.mjs         # 会话文件单元测试
│   ├── references.mjs                 # 引用语法解析与候选集分页搜索
│   ├── references.test.mjs            # 引用语法单元测试
│   ├── ui.mjs                          # 一次启动 Agent 后端与 Next.js 前端
│   ├── database.mjs                   # 动态挂载 DBHub MCP
│   └── db-demo.mjs                    # DBHub 内存数据库演示
├── src/
│   └── agent.ts                       # Thor TypeScript Agent runner
├── web/                               # Luma React / Next.js 唯一前端
│   ├── app/                           # 页面、组件、样式和本地 API 代理
│   ├── public/                        # 静态图标资源
│   └── tests/                         # Next.js 构建与渲染测试
├── .scribe-sessions/                  # 本机会话、上传文件和模型产物（不提交）
├── .env.example
├── package.json
├── backlog.md                          # 已判明原因但未实施的问题
└── readme.md
```

这套结构属于 Claude Code/Claude Agent SDK 的约定式项目体系，不是 SDK 强制生成的唯一脚手架。项目已通过 `settingSources: ["project", "local"]` 显式加载项目配置和本机覆盖，并使用 Claude Code 的 system prompt 和 tools preset，因此这些文件不仅是目录装饰，而会进入实际 SDK 运行上下文。

## 当前状态

- 根项目使用 `@anthropic-ai/claude-agent-sdk@0.3.231`、`@bytebase/dbhub@1.2.0`、TypeScript 5.9 和 `tsx`。
- Qwen Anthropic 兼容接口已验证可调用。
- Claude Code 默认工具预设已启用，包括 Windows 可用的 `Grep` 文件搜索工具。
- 已补齐项目指令、三个 Skills、三个 Subagents 和专业报告 Command。
- 已增加 JavaScript Dynamic Workflow，用于编排研究、数据核验和写作三个阶段；Qwen 网关兼容性待验证。
- DBHub 演示数据库工具链已验证；真实数据库仍需配置 `DATABASE_URL` 后测试。
- 已加入本机对话前端（`npm run ui`）：Next.js 同源 API 代理、SSE 流式输出、Markdown 渲染、工具调用折叠、子代理分流、思考过程、会话续接和成本统计。
- 前端整链路已跑通：token / Origin / Host 校验、SSE 事件流、错误传递、流式文本、思考过程、工具调用与结果配对、文件与引用、成本统计均已覆盖。根项目共 34 项单元测试，Web 有 2 项生产构建与渲染测试。
- 已加入 `@` 引用选择器：大数据量候选集在服务端分页，模型只收到 `@type:value` 短标记（见"引用语法与大候选集"）。
- `web/` 保留远程 Luma 的 React 组件、配色、圆角、布局和响应式规则；只替换数据与交互实现，没有引入 assistant-ui，也没有保留旧 `app/public/` 页面。
- 已加入应用会话文件：多文件上传、中文文件名正确显示、模型写入会话目录的产物自动出现在清单，Markdown / 文本 / 图片可在对话区预览，任意类型可下载。
- 已合并 Thor 的 TypeScript runner 与 Luma Web；远程页面组件、设计、风格和布局保持原样，原有 `app/` 功能实现继续作为可运行的 Agent 主实现。
- 运行架构已完全本地化：标准 Next.js 前端、Node Agent 后端和 `.scribe-sessions/` 文件存储，不使用 Cloudflare、D1、R2、vinext 或外部托管服务。
- 项目 Skills 已取并集，数据分析、RAG、报告写作与远程 UI/项目约定能力同时保留。
- 已强制简体中文输出，并移除在当前网关上会伪造成功的 `WebSearch`。
- `WebFetch` 已通过 `.env` 代理变量实测可用（`claude.exe` 不读 Windows 系统代理，见"WebFetch 与代理"）。
- 撰写能力已实测：一次报告任务跑了 28 轮、约 6.5 分钟，模型自主调用 Skill、Read、Glob、TaskCreate 待办和 PowerShell，产出约 9000 字带事实/推断/未知项分层和多个对比表的报告，并主动标注了未复核项与方法限制。
- 当前处于开发期全权限模式，尚未实现生产级租户和权限隔离。

### 环境变量优先级陷阱（已修复）

`app/agent-options.mjs` 使用 `dotenv.config({ override: true })`，这是必需的而非可选优化。

cc-switch 一类的供应商切换工具会往**系统环境**注入 `ANTHROPIC_BASE_URL`（例如指向 `127.0.0.1:15721`）。dotenv 默认不覆盖已存在的变量，因此 `.env` 里的百炼地址会被静默忽略，而 `ANTHROPIC_AUTH_TOKEN` 正常加载——结果是 Qwen 密钥被发往另一个网关并被拒，表现为 401，极易误判成"密钥失效"。

本项目约定密钥和连接只放 `.env`，所以 `.env` 是权威源，必须 `override`。排查同类问题时先比对 dotenv 加载前后的 `process.env`，不要先怀疑密钥。

### 已知网关限制

`WebSearch` 在当前 Qwen 兼容网关上**不真正执行搜索**：它返回 `isError: false`，但内容是模型自述"无法联网搜索"。这是伪造成功，比干净报错更危险——模型容易把编造内容当搜索结果写进报告。

**已处理**：`app/agent-options.mjs` 通过 `disallowedTools: ["WebSearch"]` 把该工具从模型上下文里移除（实测工具数 26，清单中已无 `WebSearch`），并在 system prompt 里明确当前无联网搜索能力、禁止编造搜索结果和引用。需要外部时效性事实时改用命令行工具（例如 `npm view`、`curl`）取真实数据，或明确标注该事实未经联网核实。

`WebFetch` 保留，且它**不属于网关限制**：该工具由 CLI 在本机直接发请求，不经过 Qwen 网关，因此也无法复用 Qwen 的服务端联网搜索——两者不在同一层。

### WebFetch 与代理

`claude.exe` **不读 Windows 系统代理设置**。系统代理开着、浏览器能上外网，`WebFetch` 仍然会失败，因为它只认环境变量：

```dotenv
HTTPS_PROXY=http://127.0.0.1:7897
HTTP_PROXY=http://127.0.0.1:7897
NO_PROXY=localhost,127.0.0.1,.aliyuncs.com
```

写进 `.env` 即可，`app/agent-options.mjs` 用 `env: { ...process.env }` 把它们传给 CLI 子进程。**不需要**开全局/TUN 模式。

两个容易踩的点：

- `NO_PROXY` 必须排除百炼网关（`.aliyuncs.com`），否则本该直连的国内网关流量被绕出去。
- 这几个变量对本项目自己的 Node `fetch` 不生效。Node 24 需要额外的 `NODE_USE_ENV_PROXY=1`；`claude.exe` 是 Bun 编译的，原生认 `HTTPS_PROXY`，不需要该开关。

实测：未配代理时 `WebFetch` 报 `Unable to verify if domain ... is safe to fetch`（域名安全校验要连 claude.ai，同样被墙），配好后正常返回。

能抓取不等于能搜索。没有 `WebSearch` 就无法发现 URL，只能抓已知链接；system prompt 已明确禁止猜 URL——此前 Purdue 链接 404 正是模型编 URL 导致的。

### 输出语言

harness 的系统提示是英文，模型会跟着用英文思考和回话。`app/agent-options.mjs` 在 system prompt 里显式要求简体中文，并把范围写到思考过程、进度说明、待办和最终报告上；代码、标识符、命令、路径和引用原文保持原样。只约束最终答复是不够的，思考和进度仍会漂回英文。

## 配置 Qwen

复制 `.env.example` 为 `.env`，然后填写：

```dotenv
ANTHROPIC_AUTH_TOKEN=你的百炼_API_KEY
ANTHROPIC_BASE_URL=https://你的_WORKSPACE_ID.cn-beijing.maas.aliyuncs.com/apps/anthropic
ANTHROPIC_MODEL=qwen3.7-max
```

Coding Plan 使用：

```dotenv
ANTHROPIC_AUTH_TOKEN=你的_CODING_PLAN_KEY
ANTHROPIC_BASE_URL=https://coding.dashscope.aliyuncs.com/apps/anthropic
ANTHROPIC_MODEL=qwen3.7-plus
```

`DASHSCOPE_API_KEY` 的值对应 `ANTHROPIC_AUTH_TOKEN`。`DASHSCOPE_BASE_URL` 是 OpenAI 兼容地址，不能直接用于 Claude Agent SDK；本项目不需要 `DASHSCOPE_RESPONSES_BASE_URL`。

## 运行

普通问答：

```powershell
npm start -- "分析这个项目当前具备哪些能力"
```

专业报告：

```powershell
npm start -- "/report 为管理层撰写本项目技术能力与上线风险报告"
```

动态报告 Workflow（会启动三个子代理，消耗明显高于普通问答）：

```powershell
npm start -- "/professional-report 为管理层撰写本项目技术能力与上线风险报告"
```

对话前端：

```powershell
npm run ui
```

默认打开 http://localhost:3000/ 。`npm run ui` 会先构建 Web，再以生产模式同时启动 `app/server.mjs` 和 Next.js，避免开发编译期间页面已经显示但事件尚未绑定。`app/ui.mjs` 会生成进程内 `SCRIBE_TOKEN`，浏览器不接触后端密钥。需要热更新时使用 `npm run ui:dev`；需要单独启动时可使用 `npm run ui:backend`、`npm run web` 或 `npm run web:start`。

TypeScript runner：

```powershell
npm run agent:ts -- "检查当前项目结构"
```

数据库演示：

```powershell
npm run db:demo -- "查询员工表字段，并统计员工人数"
```

语法和项目检查：

```powershell
npm test
```

## 对话前端

运行时适配层是自建薄层，不是 assistant-ui。远程 Luma 页面负责 UI，根目录 Node 服务负责 Agent：

- **AG-UI + CopilotKit / assistant-ui**：`@ag-ui/claude-agent-sdk` 是半官方适配器，但只处理 6 种 SDK 消息类型（`assistant` / `user` / `result` / `system` / `stream_event` / `thinking`），`task_*`、`hook_*`、`tool_progress` 全部丢弃，本项目的子代理和 workflow 进度会看不见；代码里也没有 `canUseTool`，接不上后续的写操作审批。它的 peer 依赖锁在 `^0.2.58`，与项目的 0.3.223 硬冲突。
- **现成 Claude Code WebUI**（cui、claudecode_webui、yepanywhere 等）：定位是"给 Claude Code 套远程壳"的编码助手，agent 配置注入权在它们手里，塞进按租户动态挂 MCP 的需求只能长期 fork。它们仍是交互设计的参考。
- **自建薄层**（当前选择）：服务层本来就在计划里（下方第 2 项），三条路都绕不开。

### 分层

- `app/agent-options.mjs`：CLI 和 HTTP 共用一份 `query()` 配置，避免两处行为漂移。
- `app/sse-events.mjs`：把 SDK 消息流翻译成紧凑 UI 事件。不做白名单——未识别类型降级成 `activity`，所以 SDK 新增消息类型不会被静默丢弃。文本只从 `stream_event` 增量取，按 `message.id` 跳过 `assistant` 里的同一段 text，避免重复渲染。
- `app/server.mjs`：Node 内置 `http` 的 API-only 后端。SSE 走 POST + `fetch` 流式读取（`EventSource` 只支持 GET，发不了 prompt）。
- `app/session-files.mjs`：每个页面会话对应 `.scribe-sessions/<id>/` 一个目录，通过 `additionalDirectories` 授权给模型。上传走 `busboy`，产物靠读目录发现。
- `app/references.mjs`：引用语法的解析、候选集分页搜索和服务端复核。数据源注册在这里，前端不参与判定。
- `web/app/`：唯一前端及同源 API 代理。页面不持有 Agent token，所有状态落在本机 `.scribe-sessions/`。

子代理输出靠非空 `parent_tool_use_id` 分流到独立气泡，`subagent_type` 和 `task_description` 显示身份。会话续接用 `result.session_id` 回传给下一轮的 `resume`。

### 当前边界

- 前端只做展示和续接，**没有工具审批**。后端仍是 `bypassPermissions`，模型可以直接读写文件和执行命令。
- 点"停止"只是断开连接，由服务端 `request.on("close")` 触发 `abortController.abort()`；没有用 `Query.interrupt()`，因此停止后会话状态可能停在中途。
- 思考内容（`thinking`）默认不显示，由顶栏"显示思考过程"开关控制，偏好存在 `localStorage`。事件始终接收并累积在 DOM 里，开关只切换 CSS 显隐，因此生成结束后再打开也能回看当轮推理。思考按纯文本渲染（推理里常有半截 markdown，解析会破坏结构），独立成块不进正文，工具调用会切分成新块。

### 会话文件

每个页面会话在 `.scribe-sessions/<appSessionId>/` 下有独立目录，并通过 `additionalDirectories` 授权给模型读写。限制：单文件 10 MB、单会话 20 个文件 / 50 MB。

- **上传**：`busboy` 必须显式设 `defParamCharset: "utf8"`。它默认按 latin1 解 `filename`，中文名会变成乱码，而且模型看到的文件名也是错的。
- **文件名**：磁盘上用随机名加原扩展名，原始名只作展示和下载名，避免路径穿越和重名覆盖。
- **产物发现**：上传记录在内存里，但模型用 `Write` 写进会话目录的报告没有记录。清单接口读一次目录做合并，标记 `source: "generated"`，因此一轮结束后前端能直接看到并下载模型生成的文件。
- **预览与下载**：token 只在请求头里，所以前端用 `fetch` 取回再转 blob，不把 token 放进 URL。Markdown / 文本 / 图片可在对话区预览，其余类型只提供下载。
- **不可信内容**：下载接口统一按 `Content-Disposition: attachment` 下发，并加 `X-Content-Type-Options: nosniff` 和 `Content-Security-Policy: sandbox`，避免同源页面里直接执行上传来的 HTML / SVG。预览的文本内容仍过 DOMPurify。system prompt 也要求模型把文件内容当数据而非指令，并要求用户明确说明每个文件的角色。

### 引用语法与大候选集

需要用户从大列表里选一项时（供应商、表、文件），把候选集喂给模型是不可行的：几万条一次几十万 token，而且与任务无关。这里的做法是**模型只拿引用，数据留在服务端**。

语法是 `@type:value`：

```text
对比 @file:app/server.mjs 和 @pkg:%40anthropic-ai/claude-agent-sdk 的接口
```

- **候选集永不进 context**。前端在 composer 里打 `@` 触发面板，按 `/api/options?source=&q=&limit=&offset=` 分页拉取，一页 20 条，滚动加载下一页。`limit` 由服务端再夹一次上限（50），所以前端不可能一次拉走整张表。
- **成本与库的大小无关**。243 个包的候选集整体灌入是 7 KB 量级；换成引用后，三条引用展开成的上下文是 463 字节，且只随引用条数增长。
- **服务端复核**。`referencePromptContext()` 对每条引用重新解析，命中才给模型真实描述，不存在的明确写成"在 X 中不存在，不要凭猜测使用"。前端传来的标签一概不采信。
- **数据源注册在 `app/references.mjs`**。当前是 `file`（项目文件）和 `pkg`（已安装依赖）。规模到十万级时把 `list()` 换成数据库查询即可，接口形状不变。

两个必须踩过才知道的点：

- **中文标点要显式排除**。`value` 用"非空白"匹配的话，`@file:a.md，然后` 会把中文逗号和后面的字吞进路径。中文里标点紧贴词尾，这是主场景而非边角情况。
- **`@` 要百分号编码**。作用域包名本身以 `@` 开头，不编码时 `@pkg:@anthropic-ai/sdk` 会在第二个 `@` 处截断。编成 `%40` 后 chip 和展开都显示解码后的原名。

后端 `app/references.mjs` 负责可信解析和复核，前端只负责识别光标附近的引用触发区间并插入服务端返回的引用文本。最终送给模型的引用始终由后端重新验证。

### 安全约束

服务默认只绑 `127.0.0.1`，并同时校验三项：`Host` 必须指向本机（阻断 DNS rebinding）、`Origin` 必须在允许列表内、`x-scribe-token` 必须匹配。自定义头会强制浏览器预检，而服务不回任何 CORS 头，跨站页面无法读取响应。

token 未通过 `SCRIBE_TOKEN` 指定时每次启动随机生成并注入页面，不存在固定默认口令。

这套校验是"开 HTTP 端口"的前置条件，不是可选加固：后端是完整 `claude_code` 工具集加 `bypassPermissions`，无认证暴露等于开一个远程代码执行接口。**即使如此也不要绑 `0.0.0.0` 或放到公网**，生产隔离仍未实现。

可调环境变量：`SCRIBE_PORT`（默认 4310）、`SCRIBE_TOKEN`、`SCRIBE_MAX_TURNS`（默认 30）。

## 数据库连接

在 `.env` 中配置以下一种格式：

```dotenv
# PostgreSQL
DATABASE_URL=postgres://USER:PASSWORD@HOST:5432/DATABASE?sslmode=require

# MySQL / MariaDB
DATABASE_URL=mysql://USER:PASSWORD@HOST:3306/DATABASE?sslmode=require

# SQL Server
DATABASE_URL=sqlserver://USER:PASSWORD@HOST:1433/DATABASE?sslmode=require

# SQLite（Windows 绝对路径）
DATABASE_URL=sqlite:///D:/path/to/database.db
```

数据库 MCP 在 `app/database.mjs` 中动态挂载，而没有写死在 `.mcp.json`。这样未来可以按租户为每次请求注入不同的连接和 MCP 实例，避免把共享凭证提交到项目配置。`.mcp.json` 保留给无需按租户变化的项目级静态 MCP 服务。

## Skills、Agents 和 Commands 的关系

- Skill 是可复用的工作标准，说明一类任务应该怎样做。
- Agent 是具有独立上下文和工具边界的角色，例如研究员、数据分析师、撰稿人。
- Command 是用户显式触发的工作入口，例如 `/report`。
- Workflow 是 JavaScript 编排脚本，把并行、分阶段和汇总逻辑固化下来，例如 `/professional-report`。
- MCP 是外部能力和数据源的连接协议，例如 DBHub 数据库工具。

它们不会自动保证报告专业或数据库安全；质量来自 Skill 的流程约束、Agent 的分工、真实工具结果和应用层权限控制共同作用。

## 当前权限说明

入口当前启用了 `permissionMode: "bypassPermissions"` 和 `allowDangerouslySkipPermissions: true`，并加载完整 Claude Code 工具集。模型可以读写项目文件、执行命令和调用已配置的 MCP。这适合本机开发验证，不应直接用于生产或多租户服务。

`.claude/settings.json` 描述项目共享的工具权限；`.claude/settings.local.json` 用于本机覆盖且已加入 `.gitignore`。当前程序级 bypass 会跳过交互审批，因此后续安全控制必须在应用层和 MCP/数据库层同时实现。

## OpenAI 模型接入边界

Codex 的 `[model_providers.<name>]` 是 Codex 自己的配置，Claude Agent SDK 不读取 `~/.codex/config.toml`。OpenAI Responses API 与 Anthropic Messages API 的请求、流式事件和工具调用协议不同，不能仅替换 API Key 和 Base URL 复用。当前项目先继续使用已验证成功的 Qwen Anthropic 兼容接口。

## 后续执行计划

1. 配置并验证真实 `DATABASE_URL`，确认网络、TLS、schema 和只读账号权限。
2. 关闭全局 `bypassPermissions`，先用容器或沙箱限定可写目录，再用 `canUseTool` 把工具审批接入现有 Web 组件，并补上工具 allowlist、文件目录边界、只读 SQL 校验及结果行数和超时限制。
3. 用 `Query.interrupt()` 替换当前“断连即中止”的停止方式，让会话状态可控。
4. 增加会话索引恢复、审计日志、敏感信息脱敏、并发限制和更完整的端到端测试。
5. 在确有多用户部署需求后，再加入 `tenantId`、`userId` 和请求级工作目录，为每个租户隔离 SDK 会话、MCP 进程、数据库凭证和文件空间。
6. 接入独立搜索 MCP 替代不可用的 `WebSearch`，并补齐 Subagents、Skills、slash commands 和 Dynamic Workflows 的网关支持矩阵。
7. 增加报告模板、业务指标字典、数据源说明和端到端报告质量评测。
8. 补上模型主动请求选择的通道（`canUseTool` + `updatedInput`）；它与工具审批共用同一条双向通道。
