# ADR-014: CCSDK Runtime 方案二 MVP

| 字段 | 内容 |
| --- | --- |
| 决策日期 | 2026-09-02 |
| 决策状态 | 已采纳 |
| 实现状态 | 部分实现 |
| 最近核对 | 2026-09-07 |
| 替代的旧 ADR | [ADR-012](012-provider-neutral-agent-runtime.md) 的 MVP 落地范围 |
| 被哪份 ADR 替代 | 无 |

## 背景

现有 Java AI 中台需要接入 Claude 长任务、Workflow、Skill 和 MCP，同时保持业务授权、可重连输出和私有观测边界。

## 决策

- 采用 Java 控制面 + Python 薄 Runtime：浏览器只向 Java 提交 conversationId、content、capabilityRef、attachmentIds；Java 从登录上下文取得身份并授权能力/文件，Python 接受可信内部 agent-run/v1 请求，不查 Java 业务库。
- Java 创建业务会话、messageId 和 runId；Runtime 目标只要求 runId，messageId/turnId 兼容字段仅作私有关联。HS256 Run JWT 绑定 sub、tenant、runId、capabilityRef、scope、jti、iat、exp；一次性 jti 仅在启动消费，查询/重连不消费。
- 业务 Bearer 不放入 JWT，仅在能力声明需要时通过 credentials.platformBearer 传给 Python，按 MCP_AUTH_RULES 注入获准的目标 header/env。
- 普通对话/问数用 query()，撰写/长任务用单 owner SessionActor 的 ClaudeSDKClient；Run 与订阅分离，公共事件持久回放，显式 cancel 才停止，公共输出仅含文本、阶段、工具生命周期和终态。
- 固定附件在执行前通过 Java File Broker 获取代理流或一次性 URL，校验后写 Run 临时目录；产物经 Java 再授权下载，细节见 ADR-016。
- MVP 不引入 capabilityVersion、credentialRef 或发布版本表；配置变更从下一 Run 生效，不承诺旧 Provider session 恢复。Workflow 图必须有显式 Runner，不能凭文件名假定执行。

## 实现证据与差距


## 后果

- 好处：统一授权入口，长任务事件可回放，业务界面与私有诊断分离。
- 代价：Java 需完成 Adapter、事件和文件服务；多实例需共享持久状态与租约等基础设施。
- 风险：本地目录、SQLite、内存缓存不足以承担多实例生产；生产需受控存储、mTLS 及非对称签名。

## 工程要求检查

| 要求 | 状态 | 依据 | 差距与后续处理 |
| --- | --- | --- | --- |
| REQ-001 | 部分满足 | Python 选择性注入与请求绑定已有实现 | Java 透传、运行中撤销和全出口验证仍缺。 |
| REQ-002 | 部分满足 | 决策限定业务前端触发能力 | 当前标识耦合、本地自由 Workflow 入口和 Java 生产授权仍有差距。 |

## 状态变更记录

| 日期 | 决策状态 | 实现状态 | 说明 |
| --- | --- | --- | --- |
| 2026-09-07 | 已采纳 | 部分实现 | 补记当前核对结果、证据与差距；不追补未知的历史状态日期。 |
