# ADR-002: 使用 MCP 动态挂载数据库

日期: 2026-08-17（2026-08-27 更新直达 workflow）
决策状态: 已采纳
实现状态: 已实现
替代: 无
被替代: 无

## 背景

Agent 需要访问数据库，但连接凭证不能写入项目配置文件或提交到 Git。

## 决策

使用 MCP（Model Context Protocol）在 Python runtime 中动态挂载数据库，而不是在 `.mcp.json` 中静态配置。Python FastAPI 服务负责启动 worker、识别 workflow 名称和转发 JSONL 事件。问数 workflow 的非敏感配置、DBHub 模板、约束和语义文件放在 `.claude/workflows/database-qa/`；workflow 专属凭据由同目录被忽略的 `workflow.env` 注入。

`database-qa` 的约束和语义由 DBProcessing `docs/model_context` 三份维护文档提炼而来，按 `constraints/`、`semantics/`、`semantics/tables/` 分层，并在 `workflow.json` 中显式登记。`not_for_model` 的完整 DDL、样例值和人工校验快照不自动进入提示词。

`database-qa` 是 `execution.mode=direct` 的单 Agent workflow profile。FastAPI 显式路由后，Python 只挂载 DB MCP，以空内置工具集启动一次 SDK `query()`；不再通过 Skill、Workflow 工具或 JS 子代理转发。多代理编排仍使用 `.claude/workflows/*.js`。

## 后果

### 好处
- 可以按租户在运行时注入不同的数据库连接
- 凭证只放在 `.env`，不提交到版本控制
- `.mcp.json` 保留给无需按租户变化的静态 MCP 服务
- Agent SDK、系统提示和数据库工具配置只有 Python runtime 一份来源，避免服务层与 worker 行为漂移
- workflow 业务配置与公共运行时解耦，新增 workflow 时不需要修改 Python worker
- 每个 workflow 可以拥有独立的环境文件和 Markdown 语义层，根 `.env` 不会堆积业务数据库变量
- 问数链路只发生一次模型 Run，避免 Skill 到 Workflow 再到子代理的重复开销

### 代价
- workflow 名称需要在 Agent 启动前解析，不能运行到中途才切换数据库 provider
- 多一层抽象，相比直接集成 ORM 更复杂
- MCP 服务需要额外进程
- DBHub 仍是 Node 进程，由 Python worker 负责拉起
- 直达 profile 不能使用文件、Skill 或子代理能力；跨能力场景应退出问数模式

### 风险
- 当前使用 DBHub，其稳定性和功能完整性依赖上游维护
