# ADR-002: 使用 MCP 动态挂载数据库

| 字段 | 内容 |
| --- | --- |
| 决策日期 | 2026-08-17 |
| 决策状态 | 已采纳 |
| 实现状态 | 已实现 |
| 最近核对 | 2026-09-07 |
| 替代的旧 ADR | 无 |
| 被哪份 ADR 替代 | 无 |

## 背景

Agent 需要访问数据库，但连接凭证不能写入受版本控制的配置或模型输入；问数配置应归属对应 Workflow。

## 决策

- 由 Python Runtime 动态挂载 DBHub MCP；FastAPI 解析 Workflow 并启动 SDK Worker、转发 JSONL，不在项目级 `.mcp.json` 写数据库凭据。
- 非敏感配置、DBHub 只读模板及约束/语义放在 `.claude/workflows/database-qa/`；专属凭据来自被忽略的 `workflow.env`。
- 语义从 DBProcessing 的模型上下文提炼，按 constraints、semantics、tables 分层并在 `workflow.json` 显式登记；`not_for_model` 的 DDL、样例和人工快照不自动注入。
- `execution.mode=direct` 由后端确定性路由，使用空内置工具集和仅 DB MCP 执行一次 `query()`，不经 Skill、Workflow 工具或子代理转发；多代理图仍属 JS Workflow。

## 实现证据与差距

- 范围与代码：[config.py](../../python/runtime/config.py) 的 `create_database_mcp_server`、`create_agent_options`，及 [profile](../../.claude/workflows/database-qa/workflow.json) 已实现本地动态挂载。
- 验证：[test_agent_worker.py](../../python/tests/test_agent_worker.py) 的 DB 工具限制、配置路径和凭据不入 Prompt 检查随本次 Python 测试通过；未重跑真实数据库问数。
- 差距：已实现只覆盖本地 DB profile；按租户选取连接与生产隔离未据此验收。2026-08-27 的直达 Workflow 调整沿用原文记录。

## 后果

- 好处：配置与执行解耦，问数仅一次模型 Run；具备按受控配置装配连接的基础。
- 代价：需要提前解析 Workflow，且 DBHub 仍依赖 Node 子进程；直达模式不具备文件、Skill 或子代理能力。
- 风险：DBHub 可用性依赖上游；动态挂载本身不能替代数据库授权或租户隔离。

## 工程要求检查

| 要求 | 状态 | 依据 | 差距与后续处理 |
| --- | --- | --- | --- |
| REQ-001 | 部分满足 | DB MCP 声明不接收业务 Token，配置测试通过 | 业务 MCP 的 Java 透传和撤销验证不在本条完成范围。 |
| REQ-002 | 部分满足 | 已有受控直达 profile | 本地 Workflow 入口不能直接开放给业务前端，Capability 解耦见 ADR-013。 |

## 状态变更记录

| 日期 | 决策状态 | 实现状态 | 说明 |
| --- | --- | --- | --- |
| 2026-09-07 | 已采纳 | 已实现 | 补记当前核对结果、证据与差距；不追补未知的历史状态日期。 |
