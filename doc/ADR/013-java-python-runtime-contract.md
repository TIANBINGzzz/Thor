# ADR-013: Java 控制面与 Python CCSDK Runtime 契约

| 字段 | 内容 |
| --- | --- |
| 决策日期 | 2026-09-02 |
| 决策状态 | 已采纳 |
| 实现状态 | 部分实现 |
| 最近核对 | 2026-09-07 |
| 替代的旧 ADR | [ADR-012](012-provider-neutral-agent-runtime.md) 的通用契约 |
| 被哪份 ADR 替代 | 无 |

## 背景

Java 掌握身份、资源 ACL 和业务会话，Python 执行 SDK；长任务不能因浏览器断线取消，公共输出与私有诊断需要分离。

## 决策

- Java 创建业务会话、messageId、runId，授权 Capability 并签发短期 Run JWT；Python 校验签名、aud/iss、时效、jti 和请求绑定，不连接 Java 业务数据库。
- 目标 Runtime 生命周期只依赖 runId；现有 Java 兼容传入的 messageId/turnId 仅作私有关联，不进入公共事件，不改变身份语义。
- `agent-run/v1` 启动，公共 `agent-events/v1` 按 runId + sequence 持久化并支持 Last-Event-ID/afterSequence 回放；SSE 只订阅，显式取消才停止 Run。
- 私有诊断仅保存 SDK 实际暴露的数据，公共事件不含思考原文、工具参数/结果、路径和凭据；原始 Token/密钥也不得进入私有观测、普通日志或业务库。
- Java 可在 credentials.platformBearer 传本次业务 Token，Python 按可信 MCP_AUTH_RULES 仅注入指定 MCP header/子进程 env；Capability 是稳定业务标识，由受控配置解析资产，能力切换默认新 session，兼容时才 resume。
- runtimeSessionRef 仅保存 Provider 不透明句柄；字段与 Java 职责分别见 [Runtime 规范](../specs/ccsdk-runtime-interface.md)、[Java 方案](../specs/java-control-plane.md)。

## 实现证据与差距

- 差距：Java 业务事件存储、跨实例订阅、运行中 Token 撤销及全部记录出口的泄漏验证未闭环；当前 protocol 仍将 capabilityRef 与 Workflow ID 绑定，不满足标识独立。

## 后果

- 好处：业务授权集中，公共事件可回放，私有故障诊断不污染业务会话契约。
- 代价：需 Java Adapter、能力注册和事件存储；单实例 SQLite 与本地 transcript 不等于生产持久基础设施。
- 风险：HS256 共享密钥泄露扩大伪造范围，生产目标为非对称签名和 mTLS；未持久化 transcript 不能保证原生 resume。

## 工程要求检查

| 要求 | 状态 | 依据 | 差距与后续处理 |
| --- | --- | --- | --- |
| REQ-001 | 部分满足 | 规则注入和配置复制已有源码/测试 | Java 真实透传、撤销及全出口无泄漏验证仍缺。 |
| REQ-002 | 部分满足 | 决策保留 Java 授权与内部资产映射 | protocol 的标识耦合及生产授权闭环仍需按清单处理。 |

## 状态变更记录

| 日期 | 决策状态 | 实现状态 | 说明 |
| --- | --- | --- | --- |
| 2026-09-07 | 已采纳 | 部分实现 | 补记当前核对结果、证据与差距；不追补未知的历史状态日期。 |
