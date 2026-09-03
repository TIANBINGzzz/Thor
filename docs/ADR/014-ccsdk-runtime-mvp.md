# ADR-014: CCSDK Runtime 方案二 MVP

日期: 2026-09-02
决策状态: 已采纳
实现状态: 部分实现
替代: 无
被替代: ADR-012

## 背景

现有 Java AI 中台负责用户、租户、会话、消息和浏览器鉴权；CCSDK/Claude
运行时需要执行长任务、Workflow、Skill 和 MCP。浏览器断线不能中止任务，
同时不能把业务 Token、原始思考或工具参数暴露给前端；故障诊断仍需要在受限范围内保留 SDK 实际暴露的观测。

## 决策

采用“Java 控制面 + Python 薄 Runtime”。浏览器只调用 Java，并提交
`conversationId`、`content`、`capabilityRef`、`attachmentIds`；Java 从登录上下文取得
`userId`/`tenantId`，创建 `businessSessionId`、业务 `messageId` 和 `runId`，再按能力
注册表派生 Runtime 模式、Workflow、Skill、MCP 和文件权限。目标契约只要求 Python 使用
`runId`；不能修改现有 Java 时，Runtime 兼容接收 `messageId`/`turnId`，但仅作为私有关联
字段，不改变生命周期语义，也不进入公共事件。Python 只接受内网
`agent-run/v1` 请求，不连接 Java 业务数据库。

Java 为每次启动签发短期 HS256 Run JWT（绑定 `sub`、`tenant`、`runId`、
`capabilityRef`、`scope`、`jti`、`iat`、`exp`）。Python 本地验签并校验请求
绑定；启动消费一次性 `jti`，查询、事件回放和重连不消费。业务 Bearer 不放
JWT；仅能力注册表声明需要时，Java 将其作为内部 `credentials.platformBearer`
传给 Python，Python 按固定 `MCP_AUTH_RULES` 注入目标 MCP 的 header/env。

普通对话和问数使用一次性 `query()` Runtime；撰写和长任务使用由单一
`SessionActor` Task 独占的 `ClaudeSDKClient`。Run 与 SSE 订阅解耦。Python MVP 已将事件以 `runId + sequence` 保存并支持回放；Java
持久化 Run/Event 后，断线再使用 `Last-Event-ID`/`afterSequence` 回放；只有显式 cancel 才停止 Run。公共事件
只包含文本增量、阶段、工具开始/结束和终态，不包含思考原文、工具参数、路径或 Token。
同一次 SDK 消息消费在公共转换前经过 `ObservationRecorder`，写入独立的
`ccsdk-observation/v1` 私有观测流；`observationId`/`observationSequence` 不复用公共序号，
可保留 SDK 实际暴露的 thinking、工具调用/结果、流式事件和 `ResultMessage`。原始凭据永不落盘，
私有观测经脱敏、限额、加密和独立权限控制后供运维/审计读取，不通过 Java 公共 SSE 暴露。

文件由 Java 文件服务/对象存储控制 ACL；Runtime 仅接收本次 Run 的短期文件引用，
下载到 Run 临时目录，产物经 Java 再次授权后提供下载。MVP 不引入
`capabilityVersion`、`credentialRef` 或发布版本表；能力变更从下一次 Run 生效，
不承诺旧 Provider session 可恢复。

## 后果

### 好处

- 身份、租户和资源权限集中在 Java；Python 保持轻量且可替换 Provider。
- 普通对话、问数和撰写都用同一能力入口；市场卡片与输入框“+”只需触发能力 ID。
- Runtime 已可回放事件；Java 完成 Run/Event 持久化后可支持跨刷新/实例重连，状态可展示但不泄露内部推理。

### 代价与风险

- 单实例 MVP 的 SQLite、内存 replay cache、本地临时目录和 transcript 不能承担多实例生产。
- Java 必须持久化 Run/Event 并提供重连接口；生产需对象存储、Redis/队列、mTLS，
  并将 HS256 换为 RS256/EdDSA。Workflow 图脚本需显式 Runner，不能仅凭文件名假装执行。
