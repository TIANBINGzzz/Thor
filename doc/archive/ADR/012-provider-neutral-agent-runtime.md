# ADR-012: Java 控制面与 Provider-neutral Agent Runtime

| 字段 | 内容 |
| --- | --- |
| 决策日期 | 2026-08-28 |
| 决策状态 | 已替代 |
| 实现状态 | 不适用 |
| 最近核对 | 2026-09-07 |
| 替代的旧 ADR | 无 |
| 被哪份 ADR 替代 | [ADR-013](013-java-python-runtime-contract.md)、[ADR-014](014-ccsdk-runtime-mvp.md) |

## 背景

Java 直接调用 Dify，Python 独立运行 Claude SDK；两条链路的会话、SSE 和 Provider 标识需要统一业务边界。

## 决策

- 保留原始决策供追溯：Java 掌握身份、租户、权限、业务会话/消息、文件授权、审计及浏览器 SSE；Python 编译 SDK/MCP/Skill 配置并执行工具、翻译事件。
- 原方案以 Adapter 接入 Dify、Claude、DeepSeek 等 Provider，使用 `agent-run/v1`、`agent-events/v1`，Provider session 仅作为不透明引用。
- 原方案区分 Workflow、Skill 和普通会话，并以短期、限定 audience/scope 的 grant 引用传凭据；仅同一 Runtime 且配置兼容时 resume，否则通过摘要/产物迁移。
- 当前依据改为 ADR-013、014；本条的 grant 等原始字段不得覆盖后续明确的 Token/MCP 契约。

## 实现证据与差距

- 范围：被替代的历史方案，不要求当前代码继续实现全部旧约定。
- 依据：[ADR-013](013-java-python-runtime-contract.md)、[ADR-014](014-ccsdk-runtime-mvp.md) 已具体化控制面、Runtime 协议与 MVP；实现进度在对应 ADR 跟踪。
- 验证与差距：本次只校正双向替代关系，未虚构旧方案的完成状态或替代发生日期。

## 后果

- 好处：保留 Provider 解耦的决策理由与演进背景。
- 代价：各 Provider 能力不同，Adapter、能力校验、Run/Event 持久化仍有实现成本。
- 风险：不能按历史 grant 方案实现当前凭据协议；隔离不足或不兼容 resume 可能泄露上下文。

## 工程要求检查

| 要求 | 状态 | 依据 | 差距与后续处理 |
| --- | --- | --- | --- |
| REQ-001 | 不适用 | 本条已替代，旧 grant 方案不再指导当前 Token 注入 | 按 ADR-013、014 和工程清单执行。 |
| REQ-002 | 不适用 | 本条已替代，当前能力注册与授权以现行工程清单为准。 | 本次不改变该要求。 |

## 状态变更记录

| 日期 | 决策状态 | 实现状态 | 说明 |
| --- | --- | --- | --- |
| 2026-09-07 | 已替代 | 不适用 | 保留历史状态并校正替代方向；不追补未知的替代日期。 |
