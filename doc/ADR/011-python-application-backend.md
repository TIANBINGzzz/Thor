# ADR-011: 应用后端统一使用 Python

| 字段 | 内容 |
| --- | --- |
| 决策日期 | 2026-08-26 |
| 决策状态 | 已采纳 |
| 实现状态 | 已实现 |
| 最近核对 | 2026-09-07 |
| 替代的旧 ADR | 无 |
| 被哪份 ADR 替代 | [ADR-018](018-extract-local-playground.md) 部分替代：本地 UI/会话/上传不再属于 Runtime 仓库；Python Runtime 决策继续有效 |

## 背景

原 Node HTTP/SSE 服务再启动 Python Worker，造成配置、测试和生命周期处理分散；Next.js 与 DBHub 仍需要 Node。

## 决策

- 认证、HTTP/SSE、会话、文件、引用、统计和启动编排统一放在 Python FastAPI 后端。
- Agent 使用独立 Python Worker，通过 JSONL 隔离 SDK；保留既有前端 API、SSE 和本地会话数据格式。
- Node.js 仅保留给 Next.js、DBHub 及现有 Node 项目脚本；此处保留既有产品契约，不新增通用兼容层。

## 实现证据与差距

- 原实现含 `python/ui.py` 和本地接口；2026-09-09 按 ADR-018 迁至独立 ScribePlayground。[server.py](../../python/server.py) 与 [process.py](../../python/runtime/process.py) 保留 Runtime 执行入口。
- 验证：本次执行 Python 全量 134 项测试通过，覆盖服务、进程、引用、文件和会话；前端与真实 Provider 链路本次未重跑。
- 差距：语言迁移已完成不等于生产接入完成；内部 Run 的回放和生命周期按 ADR-013 至 ADR-015 继续跟踪。

## 后果

- 好处：后端配置与生命周期集中，减少 Node/Python 应用桥接维护。
- 代价：完整本地界面仍需 Python 和 Node 两套运行环境。
- 风险：本地聊天流取消仍影响 Worker；内部 Run 已与订阅解耦，跨实例恢复不能由语言迁移保证。

## 工程要求检查

| 要求 | 状态 | 依据 | 差距与后续处理 |
| --- | --- | --- | --- |
| REQ-001 | 部分满足 | Python 已具备按 MCP 注入规则 | Java 透传、运行中撤销和完整泄漏回归未端到端验收。 |
| REQ-002 | 部分满足 | 具备内部协议和受控 profile | 本地 Workflow 入口及标识耦合仍有工程清单所列差距。 |

## 状态变更记录

| 日期 | 决策状态 | 实现状态 | 说明 |
| --- | --- | --- | --- |
| 2026-09-07 | 已采纳 | 已实现 | 补记当前核对结果、证据与差距；不追补未知的历史状态日期。 |
