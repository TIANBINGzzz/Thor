# ADR-013: Java 控制面与 Python CCSDK Runtime 契约

日期: 2026-09-02
决策状态: 已采纳
实现状态: 部分实现
替代: 无
被替代: ADR-012

## 背景

Java 业务层掌握用户、租户、会话、文件 ACL 和浏览器鉴权；Python 负责调用 Claude Agent SDK、MCP、Workflow 和 Skill。浏览器断线不应取消长任务，公共事件需要展示工具/思考状态的安全摘要，但不能泄露原始推理或凭据；受限诊断又需要保留 SDK 实际暴露的详细观测。

## 决策

采用“Java 控制面 + Python 薄 Runtime”。Java 创建 `businessSessionId`、业务 `messageId` 和 `runId`，按 `capabilityRef` 做 ACL，并签发短期 Run JWT。目标契约不要求 Python 使用 `messageId` 或独立 `turnId`；为兼容不能改动的现有 Java，Runtime 可以接收它们作为私有关联字段，但不改变生命周期语义，也不回传公共事件。Python 校验签名、`aud`、`iss`、时效、`jti` 和请求绑定，不连接 Java 业务数据库。

启动请求使用 `agent-run/v1`；公共响应事件使用 `agent-events/v1`，按 `runId + sequence` 持久化并支持 `Last-Event-ID`/`afterSequence` 回放。Python MVP 已提供本地回放，Java 业务事件存储和跨实例订阅属于后续阶段。SSE 订阅与后台 Run 解耦，只有显式取消才停止 Run。

同一次 `query()` 或 `receive_response()` 消息消费先经过 `ObservationRecorder`，再翻译为公共脱敏事件；不通过第二次 SDK、模型或工具调用补采集。私有 `ccsdk-observation/v1` 使用独立的 `observationId + observationSequence`，可记录 SDK 实际暴露的 thinking、工具调用/结果、流式事件和 `ResultMessage`，但不记录原始 Token、密钥或其他凭据。私有 Journal/Collector 与 Java 业务库、公共 Event Store、普通日志和浏览器 SSE 分离授权。

Java 可在内部请求的 `credentials.platformBearer` 传入当前业务 Token。Python 依据部署侧固定的 `MCP_AUTH_RULES`，仅向声明需要凭据的 HTTP/SSE MCP header 或 stdio env 注入；原始 Token 不进入 JWT、prompt、公共事件、观测 Journal、日志、会话文件或数据库。

`capabilityRef` 是不带版本的稳定业务能力 ID。目录 profile 决定 workflow、Skill、MCP 和文件策略；能力切换默认新建 Provider session，兼容时才 resume。`runtimeSessionRef` 只保存不透明的 Claude/Dify session 句柄。

Java 侧模块、业务实体、浏览器 API、Token 透传和分阶段落地见 [Java 控制面接入方案](../specs/java-control-plane.md)。

## 后果

### 好处

- Java 的身份和资源 ACL 不被 Python 或模型替代。
- Runtime 事件可按序号回放；Java 完成业务事件存储后，浏览器刷新即可重连，且公共面小、可审计。
- 普通对话、`database-qa` 和 `writing-docx` 都通过同一 Runtime 协议触发。

### 代价

- Java 需要实现 `AgentRuntimeAdapter`、Run/Event 持久化和统一 SSE 转发。
- 单进程 MVP 的 SQLite、内存 replay cache 和本地 transcript 不能直接承担多实例生产。

### 风险

- HS256 共享密钥泄露会扩大伪造范围；生产切换 RS256/EdDSA 和 mTLS。
- 未持久化 Claude transcript 时，服务重启后只能以摘要新建 session，不能保证原生 resume。
