# Java 控制面接入方案

本文只描述 Java 业务层如何接入 CCSDK Runtime。Python 的 SDK 调用、Actor、公共事件格式见 [CCSDK Runtime 接口与字段规范](ccsdk-runtime-interface.md)；本文中的字段必须与该规范保持一致。

## 1. 边界与原则

Java 是业务控制面，Python 是执行面。浏览器只访问 Java，不直接访问 Python、Claude SDK、MCP 或对象存储。

Java 负责：

- 登录用户、租户、会话和能力 ACL；
- 业务消息、Run、事件索引和审计；
- 文件上传、文件授权、Artifact 下载；
- 签发 Run JWT，并按需透传当前业务 Token；
- 把 Python 事件转换为统一浏览器 SSE。

Java 不负责：

- 拼接 Claude CLI 参数、模型参数、`cwd`、MCP URL 或 Skill 路径；
- 直接持有 `ClaudeSDKClient`、Python Task 或 MCP 进程；
- 让前端自由指定 Workflow、Skill、工具和权限；
- 把业务 Token 放入 JWT、Prompt、公共事件或日志。

私有详细观测不进入 Java 业务实体和浏览器 SSE。Python 在同一次 SDK 消息消费中写入独立的 `ccsdk-observation/v1` Journal/Collector；Java 的 `EventRelay` 只处理公共脱敏事件。若未来开放观测查询，也必须是独立的运维/审计通道，不复用业务 `run.read` 或公共事件接口。

## 2. 总体数据流

```text
浏览器
  │ Authorization + conversationId/content/capabilityRef/attachmentIds
  ▼
Java ChatController
  │ UserUtils -> userId/tenantId
  ▼
Session + Capability ACL
  │ 创建 messageId/runId，派生 runtimeMode、profile、文件 ACL
  ├──────────────► File Broker -> fileRefs（短期引用）
  ├──────────────► Credential Resolver -> platformBearer（仅声明需要时）
  └──────────────► Run JWT（iss/aud/sub/tenant/runId/scope/jti/exp）
                         │
                         ▼
                  Python /internal/v1/runs
                         │ query() 或 SessionActor + ClaudeSDKClient
                         ├──────────────► ccsdk-observation/v1 -> 受限 Journal/Collector
                         ▼
                  agent-events/v1（runId + sequence）
                         │
             Java Run/Event Store + Outbox
                         │
                         ▼
                  浏览器统一 SSE
```

浏览器刷新或 SSE 断开只表示取消订阅。Java 根据 `runId` 和 `afterSequence` 重新订阅已持久化事件；是否终止 Run 只能由显式 `cancel`/`interrupt` 决定。

## 3. Java 模块职责

| 模块 | 最小职责 | 不应承担 |
| --- | --- | --- |
| `ChatController` | 接收业务请求、返回 `runId` 和 SSE | 不直接调用 SDK |
| `ConversationService` | 校验会话归属、创建消息和标题 | 不保存 Python Task |
| `CapabilityRegistry` | `capabilityRef` 到运行模式、Workflow、Skill、MCP、文件策略的映射 | 不接受前端路径或模型参数 |
| `RunService` | 创建 Run、幂等启动、状态机、重试 | 不把重试伪装成原 Run 继续执行 |
| `RuntimeAdapter` | 调用 Python 内部 API、读取状态、发送控制命令 | 不绕过 JWT |
| `RunJwtIssuer` | 签发短期 `run.execute/read/control` JWT | 不签发长期 SDK API Key |
| `CredentialResolver` | 从当前登录上下文读取业务 Token，按能力决定是否传递 | 不写全局变量或修改进程环境 |
| `FileBroker` | 校验文件 ACL，签发短期 `fileRef` | 不把本地路径交给浏览器 |
| `EventRelay` | 持久化公共事件、SSE 转发、断点回放 | 不转发私有 thinking 或原始工具参数 |
| `ArtifactService` | 登记产物并按租户/用户授权下载 | 不暴露永久对象存储 URL |

## 4. Java 业务实体

字段是 MVP 最小集合；不引入 `turnId`、`capabilityVersion` 或独立 `idempotencyKey`。

| 实体 | 字段 | 必填 | 说明；缺失或错误 |
| --- | --- | --- | --- |
| `conversation` | `id` | 是 | 业务会话主键；缺失无法路由 |
|  | `tenantId` | 是 | 租户隔离键；不匹配返回 `403` |
|  | `ownerId` | 是 | 用户归属；不匹配返回 `403` |
|  | `agentId` | 否 | 智能体市场来源；仅用于展示和默认能力映射 |
|  | `title` | 是 | 业务标题；可由首条消息生成 |
|  | `status` | 是 | `active/archived`；非 active 不接受新 Run |
|  | `createdAt/updatedAt` | 是 | 审计和排序时间 |
| `message` | `id`（`messageId`） | 是 | 一条用户或助手消息；只在 Java 使用 |
|  | `conversationId` | 是 | 关联业务会话 |
|  | `role` | 是 | `user/assistant` |
|  | `content` | 是 | 用户正文或已脱敏的助手正文 |
|  | `status` | 是 | `pending/streaming/succeeded/failed` |
|  | `createdAt` | 是 | 消息创建时间 |
| `agent_run` | `id`（`runId`） | 是 | 一次执行尝试；重试必须新建 `runId` |
|  | `conversationId` | 是 | 校验同一业务会话串行执行 |
|  | `messageId` | 是 | 关联目标用户消息；自动重试可复用 |
|  | `capabilityRef` | 是 | 稳定能力 ID，如 `conversation`、`writing-docx` |
|  | `runtimeMode` | 是 | Java 派生的 `query/client` |
|  | `runtimeSessionRef` | 否 | Claude `session_id` 的不透明句柄；不能当任务 checkpoint |
|  | `status` | 是 | `queued/running/succeeded/failed/cancelled` |
|  | `lastSequence` | 是 | 已落库的最大公共事件序号，初始为 `0` |
|  | `errorCode` | 否 | 机器可读错误，如 `worker_lost` |
|  | `createdAt/updatedAt` | 是 | Run 状态审计 |
| `run_event` | `runId/sequence` | 是 | 联合唯一键；用于 SSE 回放和去重 |
|  | `type` | 是 | `run.started`、`phase`、`message.delta` 等公共事件 |
|  | `publicPayload` | 是 | 已脱敏 payload；禁止 Token、路径、SQL、思维链 |
|  | `occurredAt` | 是 | 事件发生时间 |
| `file_asset` | `id` | 是 | Java 文件 ID |
|  | `tenantId/ownerId` | 是 | 文件 ACL |
|  | `storageKey` | 是 | 对象存储键；不返回浏览器 |
|  | `name/mimeType/size/sha256` | 是 | 展示、配额、校验和去重 |
|  | `status` | 是 | `uploading/ready/failed/deleted`；非 ready 不可运行 |
|  | `expiresAt` | 否 | 临时文件过期时间 |
| `message_file` | `messageId/fileId` | 是 | 用户消息与附件关联 |
| `artifact` | `id/runId/messageId` | 是 | 产物归属和下载审计 |
|  | `storageKey/name/mimeType/status` | 是 | 产物索引；下载前再次做 ACL |
|  | `expiresAt` | 否 | 临时产物过期时间 |

Java 业务库不保存原始业务 Token、Claude 原始 session 内容、完整 thinking、原始工具参数/结果、Runtime 本地路径或永久下载 URL。私有观测也不保存原始 Token、密钥或其他凭据；允许保存的 SDK 详细内容必须经过脱敏、限额、加密和独立权限控制。

## 5. 能力注册表

`capabilityRef` 是前端唯一可选的能力标识。智能体卡片和输入框“+”菜单最终都提交同一个值；Java 负责把它解析为受控 profile。

```yaml
conversation:
  runtimeMode: query
  workflow: null
  skills: []
  mcpProfile: basic
  requiresBusinessToken: false
  allowFiles: true

database-qa:
  runtimeMode: query
  workflow: database-qa
  skills: []
  mcpProfile: database
  requiresBusinessToken: true
  allowFiles: false

writing-docx:
  runtimeMode: client
  workflow: writing-docx
  skills: [writing-documents]
  mcpProfile: docx
  requiresBusinessToken: false
  allowFiles: true
```

配置中不记录版本号。能力配置变更从下一次 Run 生效；能力或权限切换默认创建新的 Claude Session，并由 Java 通过 `contextSummary`、`artifactRef` 传递必要上下文。

## 6. 浏览器到 Java API

路径可适配现有 Controller，但字段语义保持不变。

### 6.1 创建消息并启动 Run

```http
POST /api/conversations/{conversationId}/runs
Authorization: Bearer <business-token>
Content-Type: application/json
```

```json
{
  "content": "根据附件撰写项目总结",
  "capabilityRef": "writing-docx",
  "attachmentIds": ["file_01"]
}
```

| 字段 | 必填 | Java 处理 |
| --- | --- | --- |
| `conversationId` | 是 | 从路径读取并校验租户/用户归属 |
| `content` | 与附件至少一个 | 空字符串不能启动 Run |
| `capabilityRef` | 否 | 缺失默认 `conversation`；未知或无权返回 `403` |
| `attachmentIds[]` | 否 | 校验文件属于当前租户/用户且状态为 `ready` |
| `Authorization` | 是 | 只用于 Java 登录鉴权；不原样作为 Python Authorization |

成功返回 `202`：

```json
{
  "runId": "run_01",
  "messageId": "msg_01",
  "status": "queued",
  "eventsUrl": "/api/runs/run_01/events"
}
```

同一 `runId` 的网络重试由 Java 或内部调用方幂等处理；如果请求内容不同，返回 `409`。用户点击“重新生成”应创建新的助手消息和新的 `runId`。

### 6.2 查询、事件和控制

```http
GET  /api/runs/{runId}
GET  /api/runs/{runId}/events?afterSequence=18
POST /api/runs/{runId}/control   {"op":"interrupt|cancel"}
```

所有接口重新校验当前用户对 `runId` 所属会话的 ACL。SSE 使用 `afterSequence`；没有该参数时读取 `Last-Event-ID`。`interrupt` 中断当前 SDK 响应，`cancel` 终止 Run 并清理尚未开始的普通消息。

## 7. Java 到 Python 的调用

Java 在写入 `conversation/message/agent_run` 后调用 Python：

```http
POST /internal/v1/runs
Authorization: Bearer <short-lived-run-jwt>
Content-Type: application/json
```

```json
{
  "protocol": "agent-run/v1",
  "runId": "run_01",
  "businessSessionId": "conv_01",
  "capabilityRef": "writing-docx",
  "input": {
    "text": "根据附件撰写项目总结",
    "fileRefs": ["fref_01"]
  },
  "runtime": {
    "mode": "client",
    "sessionRef": null
  },
  "credentials": {
    "platformBearer": "<only-when-required>"
  }
}
```

`credentials`、`fileRefs`、`contextSummary` 和 `runtime.sessionRef` 不需要时整体省略。目标请求不发送 `messageId`、`userId`、`tenantId`、模型参数、MCP URL、Workflow/Skill 路径、`cwd` 或任意工具配置。如果当前 Java 实现仍携带 `messageId`/`turnId`，Python 只兼容接收并写入私有关联上下文，不改变 Run/Session 语义，也不回传公共事件；观测接入不要求修改 Java 或前端字段。

### 7.1 Run JWT

MVP 使用 HS256；生产建议 Java 私钥签发、Python 公钥校验（RS256/EdDSA），并使用 mTLS 限制内网来源。

```json
{
  "iss": "string-ai-center-service",
  "aud": "ccsdk-runtime",
  "sub": "user-id",
  "tenant": "tenant-id",
  "runId": "run_01",
  "businessSessionId": "conv_01",
  "capabilityRef": "writing-docx",
  "scope": "run.execute",
  "jti": "one-time-random-id",
  "iat": 1760000000,
  "exp": 1760000120
}
```

Python 校验签名、`iss`、`aud`、`exp`、`jti`、`scope`，再确认 JWT 中的 `runId`、`businessSessionId`、`capabilityRef` 与请求一致。Python 不连接 Java 业务数据库；Java 在签发前完成会话、文件和能力 ACL，Python 只需共享密钥/公钥和 Redis replay cache。

### 7.2 业务 Token 透传

业务 Token 与 Run JWT 是两条链路：

1. Java 从当前请求安全上下文取得登录用户和原始业务 Token；不信任前端自行提交的 `userId` 或 `tenantId`。
2. `CapabilityRegistry` 判断本次能力是否需要业务 Token。
3. 需要时，Java 将 Token 放入内部请求的 `credentials.platformBearer`；不需要时省略 `credentials`。
4. Python 只按固定的 `MCP_AUTH_RULES` 注入目标 MCP；不允许请求体指定任意 MCP、header 名或环境变量名。
5. Python 不把 Token 写入 Prompt、事件、日志、transcript 或业务数据库；Run 完成后释放内存引用。

示例规则（部署配置，不由前端传入）：

```python
MCP_AUTH_RULES = {
    "business-mcp": {
        "credential": "platformBearer",
        "transport": "sse",
        "target": "header",
        "name": "Authorization",
        "prefix": "Bearer ",
    },
    "internal-docx": {"credential": None},
}
```

规则只允许白名单中的 MCP 使用凭据。若未来不希望 Python 接触原始 Token，再增加 Java Credential Broker 或 MCP Auth Proxy；MVP 不需要 `credentialRef`。

## 8. 文件与 Artifact

文件流程固定为：

```text
浏览器上传 -> Java 校验租户/用户 -> 对象存储 -> file_asset(ready)
发送消息 -> Java 校验 attachmentIds -> 签发短期 fileRefs
Python 下载 fileRefs -> Run/Session Workspace 子目录
Python 生成文件 -> artifact.ready -> Java 登记 Artifact
浏览器下载 -> Java ACL -> 短期地址或代理流
```

`fileRef` 至少绑定 `fileId`、`runId`、`tenantId`、`ownerId` 和过期时间；Python 不能从任意本地路径读取文件。`Claude Session` 可以恢复历史文本，但不能恢复 Workspace、文件 ACL、产物或工具进程，因此这些状态必须由 Java/对象存储独立持久化。

## 9. Workflow、Skill 和模式退出

触发链路：

```text
智能体卡片或“+”菜单
  -> capabilityRef
  -> Java ACL + CapabilityRegistry
  -> Python profile
  -> runtime.mode=query/client
  -> workflow/skill 配置
  -> query() 或 SessionActor/ClaudeSDKClient
```

普通对话和问数使用 `query()`；撰写和长任务使用 `SessionActor -> ClaudeSDKClient`。前端不直接传 `workflow`、`skill` 或文件路径。

从 Workflow/Skill 回到普通对话时，Java 将下一条消息的能力改为 `conversation`：

1. 结束或回收旧 Client Actor；
2. 默认创建新的 Claude Session，不复用不兼容的 MCP/权限上下文；
3. 必要时注入 Java 审计后的 `contextSummary` 和 `artifactRef`；
4. 后续按 `query(resume=...)` 进行普通对话。

## 10. 重连、重试和故障

- Java 先落库再调用 Python，避免 Python 已执行但 Java 没有业务记录。
- Python 事件按 `runId + sequence` 发送；Java 以联合键去重并更新 `lastSequence`。
- 浏览器断线不改变 `agent_run.status`；重连从最后序号回放。
- Run 失败后的真实重试创建新 `runId`；是否 `resume` 旧 Claude Session 要由 Java 根据副作用、Workspace、Artifact 和 transcript 状态决定。
- Python/Worker 死亡时标记 `failed(worker_lost)`，不伪装成“可继续运行”；恢复是新 Run + 可选 `resume`。
- Java 重启后由 Outbox/Reconciler 扫描 `queued/running` Run，查询 Python 状态或按租约超时收敛为失败。

## 11. 部署与分阶段实现

### MVP（单实例）

Java、Python Runtime、Redis、关系库、对象存储和 transcript 持久卷分开部署。Java 负责所有浏览器接口；Python 仅开放内网接口。Redis 保存 `jti` 防重放、事件 replay、活动 Run 租约；不保存 `ClaudeSDKClient` 或 asyncio Task。

### 实施顺序

1. **Query 闭环**：Java 创建会话/消息/Run，签发 JWT，调用 Python `query()`，转发脱敏 SSE。
2. **持久化重连**：落库 `run_event`、`lastSequence`、`runtimeSessionRef`，实现 `afterSequence` 回放和 Outbox。
3. **文件与 Token**：接入 File Broker、对象存储和 `MCP_AUTH_RULES`，完成业务 Token 按能力透传。
4. **Client 模式**：Python 实现单 owner `SessionActor`，Java 增加撰写/长任务能力映射和控制接口。
5. **生产加固**：RS256/EdDSA、mTLS、容器/沙箱、多实例租约、跨实例事件流和 Artifact 生命周期。

Java 接入完成的最低验收标准：同一用户只能访问本租户会话；重复启动幂等；刷新可回放事件；业务 Token 只到白名单 MCP；公共事件不泄露思考/工具细节；私有观测与公共 Event Store 分离；Run、Session、Client Runtime 和浏览器连接生命周期互不混淆。
