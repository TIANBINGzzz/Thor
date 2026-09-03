# CCSDK Runtime 接口与字段规范

本文定义已选定的“Java 控制面 + Python Claude Agent SDK Runtime”方案。浏览器只访问 Java；Java 负责身份、租户、业务会话、消息、文件 ACL 和能力授权；Python 负责 SDK Runtime、Workflow/Skill/MCP、Workspace、事件翻译和私有观测。Java 侧的模块职责、实体、浏览器 API 和落地步骤单独见 [Java 控制面接入方案](java-control-plane.md)。

本文是目标契约。当前代码与目标契约的差异见“现有代码改造清单”，不能把待实现项描述成已具备能力。

## 1. 核心结论

1. 普通对话、问数和一次性任务默认使用 `query()`，一次调用就是一次 Agent Run。
2. 撰写 Skill、长任务、需要中断或连续交互的 Workflow 使用 `ClaudeSDKClient`。
3. `ClaudeSDKClient` 必须由单一 `SessionActor` Task 独占，HTTP/SSE 请求不能直接持有或调用 Client。
4. 浏览器断线只取消订阅，不取消 Run，也不销毁 Actor。
5. Claude `session_id` 只恢复对话上下文，不能恢复 Python Task、CLI/MCP 进程、工具执行和内存状态。
6. Java 与 Python 使用短期 Run JWT 鉴权；业务 Bearer 作为独立敏感字段，只注入声明需要它的 MCP。
7. MVP 不新增独立 `turnId`；现有 Java 若继续发送 `messageId`/`turnId`，Python 只将其作为可选的私有关联字段接收，不把它们用于新的生命周期语义，也不回传到公共事件。
8. 观测不通过第二次 `query()`、第二次模型请求或第二次工具调用获得；它在同一次 SDK 消息消费中读取原始消息，再分别写入私有观测和公共脱敏事件。
9. “完整观测”仅指 Claude Agent SDK 实际暴露给 Runtime 的数据，包括 SDK 消息、流式事件、工具调用、工具结果、状态和最终结果；不包含 MCP 服务内部或 Provider 网关内部未暴露的数据。
10. 私有观测与公共事件是两条数据面。公共 `agent-events/v1` 保持线上安全边界；私有 `ccsdk-observation/v1` 只供受限观测管道使用，不经 Java 浏览器 SSE 暴露。

## 2. 生命周期与 ID

### 2.1 必须分开的对象

| 对象 | 标识 | 生命周期 | 持久化位置 | 能否恢复 |
| --- | --- | --- | --- | --- |
| 业务会话 | `businessSessionId` | 用户长期对话 | Java 数据库 | 可以完整读取业务消息 |
| 业务消息 | `messageId` | 一条用户或助手消息 | Java 数据库 | 可以；不发送给 Python |
| Agent Run | `runId` | 一次具体执行尝试 | Java Run 表；事件存储 | 可重订阅；不能恢复死亡 Task |
| Claude Session | `runtimeSessionRef` | Claude 历史上下文 | Java 保存句柄；Runtime 保存 transcript | 可由新 Runtime `resume` 上下文 |
| 观测流 | `observationId` + `observationSequence` | 一次 Run 的 SDK 观测记录 | 私有观测 Journal/Collector | 可回放观测记录；不能恢复 SDK 执行 |
| Client Runtime | 无公开 ID | 一次 Client connect 到 disconnect | Python 内存 | 不能序列化；只能重建 |
| Python Task | 无公开 ID | 一次 query Task 或 Actor Task | Python 内存 | 不能恢复 |
| 浏览器连接 | SSE/HTTP 连接 | 一次订阅 | 不作为业务状态 | 断开后重新订阅 |

关系不是严格的四层树：

```text
businessSessionId
  ├── messageId（Java 消息）
  │     └── runId-1（首次执行）
  │     └── runId-2（失败后的真实重试）
  └── 多个 runId 可以顺序使用同一个 runtimeSessionRef
```

`runId` 由 Java 生成。对同一个 `POST /runs` 的网络重试复用同一 `runId`，Python 幂等返回已有 Run；真正重新执行必须生成新 `runId`。Claude Agent SDK 没有平台可用的 `runId`/`queryId`，`ResultMessage.num_turns` 也不是业务回合 ID。

`messageId` 只用于 Java 将一个或多个 Run 关联到目标助手消息：首次执行和自动重试可以指向同一消息；“重新生成一份回答”若需要保留多个候选，则创建新的助手消息。公共 Python 事件只返回 `runId`，Java 通过 Run 表找到 `messageId`。私有观测可以在 Java 已传入该字段时记录 `messageId`，但它不是公共事件字段，也不是 Runtime 执行必需字段。

`observationId` 由 Python Runtime 为一次观测流生成并绑定到 `runId`；`observationSequence` 只在私有观测流内单调递增，不能复用公共 SSE 的 `sequence`。如果一次 Run 因 worker 重启产生多个观测写入片段，仍以 `runId` 作为执行关联键，并通过 `sourceEventId` 和 Journal 去重。

### 2.2 Claude Session 的准确含义

SDK 返回的 `session_id` 映射为平台的 `runtimeSessionRef`。新的 HTTP 请求、新的 `query()`、新的 asyncio Task、新的 CLI 子进程或新建的 `ClaudeSDKClient`，都可以通过 `ClaudeAgentOptions(resume=runtimeSessionRef)` 加载同一份历史上下文。

`resume` 不会恢复以下内容：

- 已死亡的 Python coroutine 或 asyncio Task；
- 旧的 Client transport、stdin/stdout reader 和 pending Future；
- 正在执行的 Bash、工具、子代理或 MCP 进程；
- 未持久化的 Workspace 中间文件、Job 阶段和临时凭据。

因此 `runtimeSessionRef` 不是任务 checkpoint。Run、Workspace、Artifact 和 Event Log 必须由平台单独保存。

## 3. 两种 SDK 运行模式

### 3.1 模式选择

| 能力 | `runtime.mode` | SDK 入口 | 默认策略 |
| --- | --- | --- | --- |
| `conversation` | `query` | `query(prompt, options)` | 每条消息新建一个 Run Task |
| `database-qa` | `query` | `query(prompt, options)` | 一次受限问数 Run |
| `writing-docx` | `client` | `ClaudeSDKClient` | 一个 SessionActor 顺序处理多轮撰写 |
| 需要中断/确认的长 Workflow | `client` | `ClaudeSDKClient` | Actor 保持 Runtime，控制通道可抢占 |

`runtime.mode=query|client` 描述 SDK Runtime 生命周期；Workflow 文件中的 `execution.mode=direct|agent` 描述 Workflow 如何编译。两者是不同维度。例如 `writing-docx` 可以是 `runtime.mode=client` 且 `workflow.execution.mode=agent`。

模式由 Java 能力注册表派生，并由 Python 本地 profile 再校验；浏览器不能自由指定。能力与模式不匹配时 Python 返回 `409 capability_profile_mismatch`。

### 3.2 `query()`：默认对话与问数

每个 `runId` 建立一个独立 asyncio Task，并只调用一次 `query()`：

```python
options = build_options(
    profile=profile,
    workspace=workspace,
    resume=request.runtime.session_ref,
    mcp_servers=bind_mcp_for_run(request),
)

async for item in query(prompt=compiled_prompt, options=options):
    observation.capture(item)                 # 同一条 SDK 消息，只读取一次
    for event in to_public_events(item):
        await public_event_store.publish(run_id, event)
await observation.finish()
```

`observation.capture(item)` 位于公共事件翻译之前，是主执行循环中的观测钩子，不是第二次执行。它读取当前已经由 `query()` 返回的 `StreamEvent`、`AssistantMessage`、`UserMessage`、`SystemMessage`、`ResultMessage` 以及 SDK 其他消息类型；同一条消息随后才转换为公共事件。观测写入采用独立的异常隔离策略，不能因观测平台短暂故障改变公共回答的字段和语义。

对于要求可证明不丢失的审计场景，`capture` 必须先写入本地受控 Journal 并完成约定的持久化确认，再允许该消息继续进入公共转换；普通线上诊断使用有界队列和异步转发。两者不能同时宣称“零延迟”和“绝对不丢失”。

约束：

- 一个 Task 只负责一个 Run；结果或错误产生后结束 Runtime。
- 同一个 `runtimeSessionRef` 不能并发执行两个 `query(resume=...)`；Python 应取得 session lease，Java MVP 则限制同一业务会话同一时刻只有一个活动 Run。
- 浏览器断线不取消 Task；显式 control 请求才取消。
- 上一轮结束后，下一个 HTTP 请求可以在新的 Task 中用 `resume` 继续上下文。

### 3.3 `ClaudeSDKClient`：撰写与长任务

正确结构：

```text
HTTP / SSE / WebSocket
          |
          v
SessionManager
          |
          v
SessionActor（唯一长期 asyncio Task）
          |
          v
ClaudeSDKClient -> Claude CLI / MCP / Workspace
```

禁止结构：

```text
HTTP Request -> shared dict[session_id] -> ClaudeSDKClient
```

也不能用全局 `asyncio.Lock` 让多个 Request Task 轮流直接操作 Client。Client 的创建、`connect()`、`query()`、`receive_response()`、`interrupt()` 和 `disconnect()` 必须全部发生在同一个 Actor Task 中。

SessionActor 的最小职责：

1. 根据 profile、Workspace、MCP 和 `runtimeSessionRef` 创建并连接 Client。
2. 从普通消息队列顺序取出 Run，同一 Actor 不并发执行两个 `client.query()`。
3. 使用独立高优先级控制队列处理 `interrupt`、`cancel` 和权限确认。
4. 在同一次 SDK 消息消费中先交给 `ObservationRecorder`，再翻译为脱敏事件并写入公共 Event Store；不能重新调用 SDK 或工具来补采集。
5. Run 结束后保持空闲；超过 `idleTtl` 才 disconnect。
6. 保存最新 `runtimeSessionRef`，但不尝试保存 Client 对象或 Task。

内部命令只保留执行需要的字段：

```json
{"type":"message","runId":"run_01","text":"继续完善第三章","fileRefs":["fref_01"]}
{"type":"control","runId":"run_01","op":"interrupt"}
```

当前 SDK 入口为：

```python
client = ClaudeSDKClient(options)
await client.connect()
await client.query(prompt, session_id="default")
async for item in client.receive_response():
    ...
await client.interrupt()
await client.disconnect()
```

`client.query(..., session_id="default")` 的参数是 SDK 出站消息协议字段，不是平台的 `runtimeSessionRef`。一个 Client 从创建到销毁只归属一个 Actor、一个 Claude Session、一套 Workspace、权限和 MCP 配置；不得用同一个 Client 切换承载多个用户 Session。

### 3.5 平台字段到 SDK 参数

| 平台字段/策略 | `query()` 实现 | `ClaudeSDKClient` 实现 |
| --- | --- | --- |
| `runtime.mode` | 选择 `query(prompt, options)` | 选择 `ClaudeSDKClient(options)` + Actor |
| `runtime.sessionRef` | 写入 `ClaudeAgentOptions.resume` | 创建 Client 时写入 `ClaudeAgentOptions.resume` |
| `input.text` | `query` 的 `prompt`（加上服务端 profile 上下文） | `client.query(prompt)` |
| `input.fileRefs` | 下载到本 Run Workspace，再编译到 prompt/工具上下文 | 下载到 Session Workspace 的本 Run 子目录 |
| `credentials.platformBearer` | 构造本 Run 的 MCP header/env | 创建或重建 Client 时构造连接级 MCP header/env |
| `runId` | Python Task、事件和取消关联 | Actor mailbox 命令、事件和控制关联 |

`runtime.sessionRef` 是 Java -> Python wire 字段；Python 返回的 `runtimeSessionRef` 是同一个不透明句柄在 Java Run/Session 表中的持久化名称。两者都映射到 Claude SDK 的 `session_id`，但不等于 `ClaudeSDKClient.query(session_id=...)` 的业务字段。

无论 Query 还是 Client，观测钩子都必须位于 SDK 消息接收循环内：Query 位于 `async for item in query(...)`；Client 位于 `receive_response()` 的同一 Actor Task。不能在 HTTP/SSE 层重新订阅 SDK，也不能通过重新执行工具来推导工具数据。

### 3.4 Client 模式的 Token 更新

HTTP/SSE MCP header 和 stdio MCP env 通常在 Client/MCP 建连时确定。每个新 Run 仍由 Java 传入当前有效业务 Bearer；Actor 不长期保存原始 Token。

如果下一轮凭据发生变化或即将过期：

1. 等当前 Run 结束或显式中断；
2. disconnect 旧 Client/MCP；
3. 用新凭据和相同 `runtimeSessionRef` 创建新 Client；
4. 继续 Claude 历史上下文，但不恢复旧 MCP 连接和内存状态。

生产若不希望 Python 接触原始 Token，可在后续引入 Java Credential Broker/MCP Auth Proxy；MVP 不需要 `credentialRef`。

## 4. Java -> Python 接口

所有接口只允许内网访问。MVP 使用 HTTPS + HS256 Run JWT；生产使用 mTLS + RS256/EdDSA。

### 4.1 启动 Run

```http
POST /internal/v1/runs
Authorization: Bearer <run-jwt>
Content-Type: application/json
```

目标最简请求：

```json
{
  "protocol": "agent-run/v1",
  "runId": "run_01",
  "businessSessionId": "conv_01",
  "capabilityRef": "writing-docx",
  "input": {
    "text": "根据附件撰写项目总结",
    "fileRefs": ["fref_01"],
    "contextSummary": "可选：仅在切换能力并新建 Claude Session 时由 Java 生成"
  },
  "runtime": {
    "mode": "client",
    "sessionRef": null
  },
  "credentials": {
    "platformBearer": "<opaque-business-token>"
  }
}
```

`credentials`、`fileRefs`、`contextSummary` 和 `runtime.sessionRef` 都是条件字段；不需要时整个字段省略。模型、Workflow 路径、Skill 路径、MCP URL、`cwd`、系统提示和 Provider 参数不允许出现在请求中。

成功响应：

```json
{
  "run": {
    "runId": "run_01",
    "status": "queued",
    "lastSequence": 0
  },
  "eventsUrl": "/internal/v1/runs/run_01/events"
}
```

新 Run 返回 `202`；同一 `runId` 和相同请求摘要的网络重试返回 `200`；同一 `runId` 携带不同内容返回 `409`。

### 4.2 查询 Run

```http
GET /internal/v1/runs/{runId}
Authorization: Bearer <run-read-jwt>
```

```json
{
  "runId": "run_01",
  "status": "running",
  "runtime": {"mode": "client", "sessionRef": "claude-session-id"},
  "lastSequence": 18,
  "error": null,
  "createdAt": 1760000000000,
  "updatedAt": 1760000030000
}
```

`status` 只使用 `queued|running|succeeded|failed|cancelled`。进程丢失使用 `failed + error.code=worker_lost`，不伪装成可继续执行。

### 4.3 订阅或回放事件

```http
GET /internal/v1/runs/{runId}/events?afterSequence=18
Authorization: Bearer <run-read-jwt>
Last-Event-ID: 18
Accept: text/event-stream
```

事件：

```text
id: 19
event: message.delta
data: {"protocolVersion":"agent-events/v1","eventId":"evt_19","runId":"run_01","sequence":19,"type":"message.delta","payload":{"textDelta":"正文"},"occurredAt":1760000031000}
```

`afterSequence` 优先；未提供时读取 `Last-Event-ID`。浏览器或 Java 断开不会取消 Run。终态事件后仍保留一段回放 TTL。

### 4.4 控制 Run

```http
POST /internal/v1/runs/{runId}/control
Authorization: Bearer <run-control-jwt>
Content-Type: application/json

{"op":"interrupt"}
```

| `op` | 含义 |
| --- | --- |
| `interrupt` | 中断当前 SDK 响应；Client Actor 可继续服务下一条消息 |
| `cancel` | 将当前 Run 置为取消，并从普通消息队列移除尚未开始的命令 |

Query 模式通过取消对应 Run Task 实现；Client 模式必须把 control 命令送入 Actor 的独立控制通道。

## 5. 字段规范

### 5.1 浏览器 -> Java

| 字段 | 必填 | 含义 | 缺失/错误 |
| --- | --- | --- | --- |
| `conversationId` | 是 | Java 业务会话 | `404/403`，不调用 Python |
| `content` | 与附件二选一 | 用户输入 | 两者都空时 `400` |
| `attachmentIds[]` | 否 | Java 文件库中的文件 ID | 越权、未完成或过期 `403` |
| `capabilityRef` | 否 | 功能/智能体能力；默认 `conversation` | 未发布或无权使用 `403` |
| `Authorization` Header | 是 | 业务登录 Token | Java 鉴权失败；不会直接给浏览器返回 Runtime 细节 |

浏览器不得提交 `userId`、`tenantId`、`runtime.mode`、`runtimeSessionRef`、Workflow/Skill 路径、MCP 配置、Token 注入规则或模型参数。

### 5.2 Java 业务实体与观测存储

| 实体 | 最小字段 | 原因 |
| --- | --- | --- |
| `conversation` | `id, tenantId, ownerId, agentId?, title, status, createdAt, updatedAt` | 业务会话和 ACL 的唯一事实源 |
| `message` | `id, conversationId, role, content, status, createdAt` | 保存用户输入和助手结果 |
| `agent_run` | `id, conversationId, messageId, capabilityRef, runtimeMode, runtimeSessionRef?, status, lastSequence, errorCode?, createdAt, updatedAt` | 将业务消息与每次实际执行关联 |
| `run_event` | `runId, sequence, type, publicPayload, occurredAt` | 公共 SSE 回放和业务审计；可先用 Redis Stream |
| `observation_journal`（非 Java 业务实体） | `observationId, observationSequence, runId, eventType, privatePayload, occurredAt` | Python/Collector 的 SDK 详细观测存储；与公共事件、业务消息和普通日志分开授权 |
| `file_asset` | `id, tenantId, ownerId, storageKey, name, mimeType, size, sha256, status, expiresAt?` | 文件归属和对象存储索引 |
| `message_file` | `messageId, fileId` | 文件与业务消息关联 |
| `artifact` | `id, runId, messageId, storageKey, name, mimeType, status, expiresAt?` | 生成物注册和下载授权 |

Java 业务库和公共 `run_event` 不保存原始 Token、思维链、工具参数/结果、永久下载 URL 和 Runtime 本地路径。`observation_journal` 不是 Java 业务实体，而是 Python/Collector 的独立私有存储；若启用受限观测，详细 thinking、工具参数和工具结果只进入该存储，不进入业务消息正文或公共事件。仍不建 `turn` 表，不保存 `capabilityVersion`；`runId` 本身就是启动幂等键，不再增加 `idempotencyKey`。

### 5.3 Run JWT

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

| Claim | 必填 | 校验 | 缺失/错误 |
| --- | --- | --- | --- |
| `iss` | 是 | 固定 Java issuer | `401` |
| `aud` | 是 | 必须为 `ccsdk-runtime` | `401` |
| `sub` | 是 | Java 已认证用户；用于隔离上下文 | `401` |
| `tenant` | 是 | Java 已认证租户 | `401` |
| `runId` | 是 | 与 path/body 一致 | `401` |
| `businessSessionId` | 是 | 与 body 一致 | `401` |
| `capabilityRef` | 是 | 与 body 和 Python profile 一致 | `401/409` |
| `scope` | 是 | `run.execute`、`run.read` 或 `run.control` | `403` |
| `jti` | 是 | execute/control 原子防重放 | `401` |
| `iat/exp` | 是 | 有效期建议不超过 120 秒 | `401` |

Python 不连接 Java 业务数据库来验证 JWT。它使用共享密钥或 Java 公钥验证签名，再验证固定 claims、请求绑定和 replay cache。Java 在签发前已经完成会话、文件和能力 ACL。

### 5.4 Java -> Python 请求

| 字段 | 必填 | 来源/用途 | 缺失/错误 |
| --- | --- | --- | --- |
| `protocol` | 是 | 固定 `agent-run/v1` | `400` |
| `runId` | 是 | Java Run 主键 | `400`；与 JWT 不同 `401` |
| `businessSessionId` | 是 | Actor/Workspace 隔离键的一部分 | 与 JWT 不同 `401` |
| `capabilityRef` | 是 | 选择受控 profile | 未注册或模式不符 `409` |
| `input.text` | 与文件二选一 | 用户输入 | 两者都空 `400` |
| `input.fileRefs[]` | 否 | Java 签发的短期文件引用 | 越权或过期 `403` |
| `input.contextSummary` | 否 | 能力/权限切换后新 Session 的上下文摘要 | 缺失则新 Session 无旧上下文 |
| `runtime.mode` | 是 | `query|client`，由 Java registry 派生 | 非法 `400`；profile 不符 `409` |
| `runtime.sessionRef` | 否 | Claude `session_id` 不透明句柄 | 缺失则创建新 Session；无 transcript 时 resume 失败 |
| `credentials.platformBearer` | 按能力 | 当前请求的业务 Bearer | 需要它的 MCP 无值时 `401/403` |

`sub/tenant` 只从已验签 JWT 读取，不在 body 重复传。目标最简请求不需要 `messageId` 和 `turnId`；在不能修改现有 Java 的接入阶段，Runtime 可以继续兼容接收它们，并只把它们写入私有观测上下文。它们不改变 Run、Session 或重试语义，也不进入公共事件。

### 5.5 Python Actor 内部字段

| 字段 | 含义 | 约束 |
| --- | --- | --- |
| `sessionKey` | `tenant + sub + businessSessionId + capabilityRef` 的内部键 | 只映射到 Actor mailbox，不向 Request 暴露 Client |
| `runId` | 当前命令所属 Run | 事件、取消和终态都按它记录 |
| `runtimeSessionRef` | Actor 绑定的 Claude Session | 一个 Actor 只绑定一个 Session |
| `messageQueue` | 普通用户消息 | 严格顺序消费 |
| `controlQueue` | interrupt/cancel/permission | 高优先级，不排在普通消息后面 |
| `subscribers` | 当前事件订阅者 | 断开只移除订阅者 |
| `idleDeadline` | 空闲销毁时间 | 仅在没有活动 Run 且队列为空时生效 |

Redis 或数据库中不保存 `ClaudeSDKClient`、asyncio Task、Queue 对象或 pending Future。

### 5.6 公共事件

| 类型 | payload | 前端展示 |
| --- | --- | --- |
| `run.started` | `{}` | 已开始 |
| `phase` | `{"name":"thinking|working|responding"}` | 正在分析/处理/生成，不展示思考内容 |
| `message.delta` | `{"textDelta":"..."}` | 回答正文增量 |
| `tool.started` | `{}` | 正在调用工具，不展示工具名和参数 |
| `tool.finished` | `{"status":"succeeded|failed"}` | 工具调用结束 |
| `artifact.ready` | `{"artifactRef":"...","name":"...","mimeType":"..."}` | 可下载产物；URL 仍由 Java 签发 |
| `run.completed` | `{"usage":{...}}`，可选 | 完成 |
| `run.failed` | `{"code":"...","message":"安全提示"}` | 失败 |
| `run.cancelled` | `{}` | 已取消 |

每条公共事件固定包含 `protocolVersion,eventId,runId,sequence,type,payload,occurredAt`。公共事件不包含 thinking 原文、工具名称、工具参数/结果、SQL、MCP URL、绝对路径、Token、Claude `session_id` 或堆栈。

### 5.7 私有观测事件

私有观测事件使用独立的 `ccsdk-observation/v1` 契约，不复用公共 `agent-events/v1`、Java 业务 `run_event` 或浏览器 SSE。它可以记录 SDK 实际暴露的详细内容，但必须经过独立的敏感信息处理、访问控制、加密和保留周期管理。

一次 Run 的观测流示例：

```json
{
  "schema": "ccsdk-observation/v1",
  "observationId": "obs_01",
  "observationSequence": 18,
  "runId": "run_01",
  "traceId": "trace_01",
  "businessSessionId": "conv_01",
  "messageId": "msg_01",
  "turnId": "turn_01",
  "capabilityRef": "database-qa",
  "runtimeSessionRef": "claude-session-id",
  "scope": "main",
  "source": "claude-agent-sdk",
  "sourceEventId": "sdk-event-uuid",
  "eventType": "tool.call",
  "occurredAt": 1760000031000,
  "data": {
    "toolCallId": "toolu_01",
    "name": "mcp__db__execute_sql",
    "input": {}
  }
}
```

字段约束：

| 字段 | 必填 | 含义 | 规则 |
| --- | --- | --- | --- |
| `schema` | 是 | 私有观测协议版本 | 固定 `ccsdk-observation/v1` |
| `observationId` | 是 | 一次 Run 的观测流标识 | Runtime 生成；不作为业务 Run ID |
| `observationSequence` | 是 | 私有观测流序号 | 每个 `observationId` 单调递增；不复用公共 `sequence` |
| `runId` | 是 | 对应的 Agent Run | 与执行和公共事件关联 |
| `traceId` | 是 | 跨组件观测关联根 | Java 传入则沿用；缺失时 Runtime 使用 `runId` |
| `businessSessionId` | 否 | 业务会话关联 | 有值时记录；不向公共事件扩散 |
| `messageId` | 否 | 业务消息关联 | 有值时记录；不改变公共协议 |
| `turnId` | 否 | 当前实现仍可能传入的兼容关联字段 | 不作为新的生命周期对象 |
| `runtimeSessionRef` | 否 | Claude Session 句柄 | 仅私有观测可见；不得进入浏览器或普通日志 |
| `scope` | 是 | 主 Agent、子代理或嵌套工具上下文 | 使用 `main` 或稳定的 `sub:<parentToolUseId>` |
| `source` | 是 | 数据来源 | `claude-agent-sdk`、`mcp-hook` 或 `runtime` |
| `sourceEventId` | 否 | SDK 原始 UUID 或稳定事件键 | 用于重放去重；不能替代 `observationSequence` |
| `eventType` | 是 | 观测事件类型 | 见下方事件分类 |
| `occurredAt` | 是 | 事件发生时间 | Unix 毫秒时间戳 |
| `data` | 是 | 事件详细数据 | 按事件类型变化；先脱敏再落盘 |

建议的 `eventType`：

| 事件类型 | `data` 主要内容 | 数据来源 |
| --- | --- | --- |
| `sdk.message` | SDK 消息类型、字段和消息 UUID | `AssistantMessage`、`UserMessage`、`SystemMessage`、`ResultMessage` |
| `sdk.stream` | 原始流事件类型、原始增量和父工具上下文 | `StreamEvent` |
| `thinking.delta` | thinking 增量、所属 scope 和消息 UUID | `ThinkingBlock` 或 thinking stream delta |
| `message.delta` | 正文增量 | `TextBlock` 或 text stream delta |
| `tool.call.started` | `toolCallId`、工具名称、完整或累计 input、父工具 ID | `ToolUseBlock`、SDK tool lifecycle hook |
| `tool.input.delta` | 工具参数增量 | `StreamEvent` 的 input JSON delta |
| `tool.result.succeeded` | `toolCallId`、结果内容、结果大小和耗时 | `ToolResultBlock`、PostToolUse |
| `tool.result.failed` | `toolCallId`、错误标记、脱敏错误和耗时 | `ToolResultBlock`、PostToolUseFailure |
| `agent.started` / `agent.finished` | 子代理标识、父工具 ID、状态和耗时 | SDK System/Task 事件 |
| `run.finished` | 最终状态、session、耗时、turns、token、cost、stop reason | `ResultMessage` |
| `run.exception` | 异常类型、稳定错误码、脱敏堆栈摘要 | Query/Client 接收循环异常 |
| `observation.truncated` | 截断原因、已写字节、丢弃类型和计数 | 观测限额保护 |

`sdk.stream` 与 `sdk.message` 可能描述同一逻辑内容，但它们代表不同的 SDK 数据层级，不能因为内容相似就重新执行或重新调用工具。观测记录应使用 `source`、`sourceEventId`、`messageUuid`、`toolCallId` 和 `phase=delta|final` 区分；公共正文则继续按现有规则去重和合并。

“完整”有明确边界：观测器必须在 `clip()`、公共事件压缩或异常消息裁剪之前捕获原始 SDK 数据；但它只能获得 SDK 返回的字段。MCP 服务器内部 SQL、下游 HTTP、数据库驱动重试和 Provider 网关内部路由不属于 SDK 可见范围，必须在对应 MCP、数据库代理或 Provider 网关单独观测。

私有观测不得写入公共 `RunStore` 的 `run_events`，不得经 `/internal/v1/runs/{runId}/events` 返回，也不得通过 Java `run.read` JWT 或浏览器 SSE 直接暴露。Java 和前端不需要新增字段；若 Java 已提供 `messageId`、`businessSessionId` 或 `traceId`，Runtime 只将其作为私有关联上下文使用。

## 6. JWT 与业务 Token 双链路

### 6.1 Python JWT 验证顺序

```text
Authorization: Bearer <run-jwt>
  -> 限定算法并验证签名
  -> 验证 iss / aud / iat / exp
  -> 验证 scope
  -> 验证 path/body 的 runId、businessSessionId、capabilityRef
  -> execute/control：Redis SET jti NX EX；单实例 PoC 可用进程内 TTL Map
  -> 验证 capability profile 与 runtime.mode
  -> 通过后才创建 Run Task 或投递 SessionActor
```

读取状态和 SSE 时，Java 为每次内部连接签发短期 `run.read` JWT；read 请求不消费一次性 `jti`。启动和控制请求消费 `jti`。生产使用 Redis 让多实例共享 replay 状态。

### 6.2 业务 Token 传递

Java 从已认证浏览器请求的 `Authorization` Header 取得业务 Token。只有能力注册表声明需要业务 MCP 时，才在 Java -> Python 私网请求中附加：

```json
{"credentials":{"platformBearer":"<opaque-business-token>"}}
```

业务 Token 不放进 JWT，因为 JWT 的 claims 可被持有者读取；签名只防篡改，不提供保密。

Python 使用服务端固定规则注入：

```python
MCP_AUTH_RULES = {
    "business": {
        "required": True,
        "transport": "http",
        "header": "Authorization",
        "prefix": "Bearer ",
        "lifecycle": "connection",
    },
    "db": {"required": False, "transport": "stdio"},
    "docx": {"required": False, "transport": "stdio"},
}
```

注入规则：

- HTTP/SSE MCP：复制 MCP 配置，只给目标 server 增加 header。
- stdio MCP：只给该 MCP 子进程的 `env` 增加变量。
- 不修改全局 `os.environ`，不把 Token 作为模型可见工具参数。
- `required=false` 的 MCP 不读取 Token；未注册 MCP 直接拒绝。
- Run 结束或 Client 重建后释放 Token 引用；日志和异常必须脱敏。

### 6.3 观测写入与可靠性

观测是主执行循环中的一次额外处理，不是第二次 SDK 调用。每条 SDK 消息只从 `query()` 或 `receive_response()` 取得一次，然后按以下顺序处理：

```text
SDK message
  -> 原始消息归一化与敏感信息处理
  -> 私有 Observation Journal / Collector
  -> 公共事件翻译
  -> Java SSE / 浏览器
```

观测器必须位于 `clip()`、公共事件压缩和业务正文持久化之前。它不能在公共事件阶段重新拼接 thinking 或工具结果，也不能通过再次调用模型或工具补采集。`StreamEvent` 的增量和后续 typed message 即使描述相同逻辑内容，也必须分别标记来源和 `delta|final` 阶段，不能把重复事件误当成重复执行。

观测等级由 Runtime 部署配置决定：

| 等级 | 保存内容 | 适用场景 | 可靠性含义 |
| --- | --- | --- | --- |
| `off` | 不保存详细观测，仅保留运行必要日志 | 默认关闭 | 不提供执行回放 |
| `metadata` | 状态、耗时、模型、token、工具数量、错误码、关联 ID | 日常线上监控 | 允许异步转发；可能丢失少量指标 |
| `full` | SDK 实际暴露的原始消息、thinking、工具调用、参数、结果和异常 | 联调、故障诊断、短期取证 | 必须经过独立 Journal；受大小和保留期限限制 |

`full` 不能同时承诺零延迟和绝对不丢失。若审计要求“可证明不丢失”，应使用同步追加并持久化确认的受控 Journal，并在观测存储不可用时按部署策略阻止新的有副作用执行；若线上优先保障回答可用性，则使用有界缓冲、异步转发和 `observation.truncated`/`observation.dropped` 记录，明确这是尽力观测。

无论哪种等级，观测器都必须：

- 对 Token、Authorization、密码、API Key、连接串、签名和常见凭据格式做键名与内容双重脱敏；
- 设置单事件、单 Run、单租户和全局字节上限，超限时停止详细内容并记录原因；
- 将私有 Journal 与业务数据库、公共 Event Store、Claude transcript 和普通应用日志分开授权；
- 对 `run.exception`、取消、超时、worker 退出和观测写入失败记录稳定错误码，不写入原始堆栈或秘密；
- 观测写入失败不能静默覆盖为成功，也不能修改公共事件的字段语义；
- 只允许受限运维/审计身份读取，不能通过浏览器、Java `run.read` 或公共 SSE 直接读取。

OTel Span、Metrics 或普通日志只保存 `runId`、`traceId`、能力、状态、耗时、token、工具计数和错误码等低敏索引。完整 thinking、工具参数和结果放在受限 Journal 或专用观测 Collector；若要看到 MCP 内部 SQL、下游 HTTP、数据库驱动重试或 Provider 网关路由，必须在相应 MCP、数据库代理或网关单独埋点，不能假设 Agent SDK 可以代替这些观测。

## 7. 文件、Workspace 与 Artifact

### 7.1 上传与使用

```text
浏览器上传 -> Java 文件服务 -> 对象存储
发送消息 -> Java 校验 tenantId/ownerId/conversationId/file status
          -> 为本 Run 签发短期 fileRef
Python    -> 下载到 workspace/<runId>/input/
          -> 中间文件放 workspace/<runId>/work/
          -> 生成物放 workspace/<runId>/output/
          -> 上传/登记 Artifact，仅返回 artifactRef
下载      -> 浏览器请求 Java -> Java ACL -> 短期下载地址/流
```

`fileRef` 是不透明、短期、绑定 `runId + fileId + tenant + user + permission` 的访问授权，不是本地路径。Python 不能接收浏览器传来的永久 URL、对象存储 key 或任意 `cwd`。

### 7.2 会话与文件隔离

- Java 是文件和归属的唯一事实源；Python Workspace 只是缓存和执行目录。
- Query 模式每 Run 使用独立目录。
- Client 模式可以有 Session Workspace，但每个 Run 仍使用独立输入/工作/输出子目录。
- Actor 只能访问本 Session 已授权文件；切换租户、用户或业务会话必须创建新 Actor。
- 临时目录按 TTL 清理；已注册 Artifact 先上传对象存储，再清理本地文件。

## 8. Workflow、Skill 与权限切换

### 8.1 触发链路

前端的智能体卡片或输入框“+”只提交 `capabilityRef`：

```text
选择“普通对话” -> capabilityRef=conversation
选择“问数”     -> capabilityRef=database-qa
选择“撰写”     -> capabilityRef=writing-docx
选择智能体       -> Java 将 agentId 映射为其默认 capabilityRef
```

Java capability registry 决定 ACL、`runtime.mode` 和是否需要业务 Token；Python profile registry 决定实际 Workflow、Skill、MCP、模型和权限配置：

| `capabilityRef` | Runtime | Workflow | Skill | MCP |
| --- | --- | --- | --- | --- |
| `conversation` | `query` | 无 | 普通会话允许的 Skills | 受控通用 MCP |
| `database-qa` | `query` | `database-qa` / `direct` | 无或受限分析规则 | 只读 DB MCP |
| `writing-docx` | `client` | `writing-docx` / `agent` | `writing-documents` | DOCX/Artifact MCP |

Python 必须从已部署 profile 加载这些值，不能根据用户自然语言临时扩大工具、Skill 或 MCP。

`.claude/workflows/professional-report.js` 是脚本型编排；只有显式 Workflow Runner 才能执行。仅检查文件存在不等于执行 Workflow。

### 8.2 Workflow 模式退出

Workflow/Skill 权限不能在正在运行的 Client 内热切换。退出撰写或问数模式时：

1. 当前 Run 已结束则直接退出；仍在运行时由用户明确选择继续或 `cancel`，SSE 断开不代表退出。
2. Java 将下一条消息的 `capabilityRef` 改为 `conversation`。
3. 能力发生变化时 MVP 总是创建新 Claude Session，即 `runtime.sessionRef=null`。
4. Java 可通过 `input.contextSummary` 注入必要的已审计摘要和 `artifactRef`，保持业务会话连续。
5. 旧 Client Actor 空闲后由 idle TTL 销毁；不得把写作 Client 的工具权限带入普通对话。

同一能力、同一用户/租户、同一 Workspace 和权限未变化时，才允许继续使用原 `runtimeSessionRef`。MVP 不记录能力版本；配置变更只影响下一次新建 Runtime，已连接 Client 继续使用 connect 时的配置直到结束或被重建。

## 9. 断线、重连与故障恢复

### 9.1 浏览器刷新或 SSE 断开

```text
浏览器刷新
  -> Java 查询 conversation 的活动 agent_run
  -> 得到 runId + lastSequence
  -> Java 用 run.read JWT 连接 Python/事件存储
  -> GET events?afterSequence=<lastSequence>
  -> 回放后继续订阅
```

不能重新调用 `POST /runs`，否则可能重复执行有副作用的工具。Client Actor 和 Query Task 是否继续，只由 Run 状态和显式 control 决定。

### 9.2 Runtime 空闲后恢复对话

- Query：下一条消息创建新 Task，并以 `resume=runtimeSessionRef` 恢复上下文。
- Client：SessionManager 创建新 Actor，Actor 创建新 Client，并以 `resume=runtimeSessionRef` 恢复上下文。
- 两者恢复的都是 Claude 历史，不是原 Runtime 内存。

### 9.3 Python/Worker 在 Run 中死亡

租约到期后将 Run 标记为 `failed(worker_lost)`。如果需要重试，Java 新建 `runId`。只有在工具副作用可确认、Workspace/Artifact 状态完整且 transcript 可用时，才允许新 Run `resume`；否则使用新 Session + `contextSummary`。

## 10. 持久化与部署

| 内容 | 单机 PoC | 多实例/生产 |
| --- | --- | --- |
| Conversation/Message/Run | Java 业务数据库 | Java 业务数据库，唯一事实源 |
| 公共事件 | Python SQLite | Redis Stream；终态/索引可落 Java DB |
| 私有详细观测 | 每 Run 独立、权限受限的追加式 Journal | 加密观测存储或专用 Collector；按租户/运维权限读取 |
| 观测指标/链路 | 进程内日志或本地 Metrics | OTel Collector/企业观测平台；只放低敏索引和指标 |
| JWT `jti` | Python 内存 TTL Map | Redis `SET NX EX` |
| Query session lease | 进程内锁 | Redis lease/分布式锁 |
| Client Actor 定位 | 单 Python 进程 Map | Redis 保存 `sessionKey -> workerId + lease`，请求路由到 owner worker |
| Claude transcript | 受控本地 `CLAUDE_CONFIG_DIR` | 加密共享卷/PVC，或 SDK `SessionStore` |
| Workspace/Artifact | 本地隔离目录 | 对象存储 + 每 Run 临时卷 |
| Runtime 隔离 | 开发机进程 | 容器、网络策略、CPU/内存/时长限制 |

Redis 只保存事件、租约、Actor 定位和 replay 状态，不保存业务会话全文，也不序列化 Client。活跃 Client Actor 不能无缝迁移；故障后只能在其他 Worker 创建新 Actor，通过 transcript + `runtimeSessionRef` 恢复上下文。

私有观测 Journal 不属于公共事件回放源。公共 SSE 只读取 `agent-events/v1`；观测读取必须经过独立的运维/审计通道，并按 `tenantId`、用户、能力和保留期限执行授权。Runtime 重启后可以继续上传已经落盘的 Journal，但不能据此恢复正在运行的 SDK Task、工具进程或 Client。

建议把 Query Worker 和 Client Actor Worker 分成两个池：Query 可以水平扩展并按 Run 调度；Client 需要 session affinity、idle TTL 和更严格的资源上限。

Claude transcript 必须和业务文件、日志分开授权。若容器销毁后 transcript 不存在，即使 Java 保存了 `runtimeSessionRef` 也无法原生 resume，只能用业务消息摘要创建新 Session。

## 11. 现有代码改造清单

本轮只更新方案，未修改以下业务代码。

| 层 | 当前状态 | 目标改造 |
| --- | --- | --- |
| Python `runtime/protocol.py` | 支持旧的 `messageId/turnId/execution/runtime` 字段；无 `runtime.mode` | 收敛到本文最简 body；增加 `runtime.mode`，删除跨层 `messageId/turnId` |
| Python `server.py` | 每 Run 启动 `query()` worker；SQLite 事件回放；只保存公共脱敏事件 | 保留 QueryExecutor；新增 SessionManager、Actor 投递和 control 路由；在公共转换前交给 ObservationRecorder |
| Python `agent_worker.py` | 已能读取部分 typed SDK 消息并转换为事件；`clip()` 前无私有观测 | 在同一 SDK 消息循环中捕获 `StreamEvent`、typed message、工具生命周期和 `ResultMessage`；异常路径补齐观测终态 |
| Python `runtime/observability.py` | 尚未实现 | 新增 ObservationRecorder、`ccsdk-observation/v1`、脱敏、序号、大小限制、Journal 和 Collector 转发；不重新调用 SDK/工具 |
| Python Runtime | 未实例化 `ClaudeSDKClient` | 新增单 owner `SessionActor`，普通队列、控制队列、idle TTL 和 session lease；Query/Client 共用同一观测语义 |
| Python MCP auth | 已有按规则注入雏形 | 增加 Client 连接级 Token 更新/重建策略，确认无全局环境污染 |
| Python storage | SQLite、进程内活动 Run、本地 transcript；无私有观测存储 | 公共事件与私有观测 Journal 分离；生产接 Redis/队列、受控 `CLAUDE_CONFIG_DIR` 或 `SessionStore`、对象存储和加密观测存储 |
| Java Request DTO | 仍发送 `messageId/turnId` 和多余 Runtime 字段 | 观测方案不要求修改字段；Runtime 兼容接收现有 `messageId/turnId`，仅用于私有关联；公共协议保持不变 |
| Java capability registry | 已有 `conversation/database-qa/writing-docx` | 增加 `runtimeMode`；`writing-docx=client`，其余默认 `query` |
| Java bridge | 浏览器 SSE 与一次同步桥绑定 | Run 先落库；订阅与执行解耦；按 `runId + sequence` 重连 |
| Java persistence | 尚未形成完整 Run/Event/Session 闭环 | 保存 Run 状态、`lastSequence`、`runtimeSessionRef`、活动 Run 查询 |
| Java files | 附件 ID 到 Runtime 的 ACL/File Broker 未闭环 | 校验归属后签发短期 `fileRef`，Artifact 下载继续经过 Java |
| 前端 | 已有能力入口和流式展示基础 | 无需为私有观测增加字段；继续只展示 phase/tool 状态，公共 SSE 仍使用 `runId/sequence` |

## 12. 分阶段落地

| 阶段 | 可用目标 | 验收重点 |
| --- | --- | --- |
| 1. 最小闭环 | 普通对话/问数走 Query；撰写走单实例 SessionActor + Client；同一次 SDK 消费同时生成私有观测和公共脱敏事件 | 同 Session 不并发、Client 单 owner、Token 不进公共事件；thinking/tool/ResultMessage 可在 SDK 观测中关联 |
| 2. 可恢复 | Java Run/Event 持久化、活动 Run 查询、SSE 回放、transcript 持久卷、File Broker；私有 Journal 可补传 | 刷新不断任务；Actor 空闲后可用 sessionRef 恢复下一轮；观测序号和公共序号互不影响 |
| 3. 可上线 | Redis event/lease/jti、对象存储、容器隔离、RS256/EdDSA+mTLS | 多实例无重复执行、跨租户 403、Worker 丢失可判定 |
| 4. 完善 | Credential Broker、审批/等待输入、脚本 Workflow Runner、观测查询授权、指标和告警 | 凭据轮换、长任务治理、观测保留/审计/灾备；MCP 内部和 Provider 网关观测单独建设 |

## 13. 字段级桑基图

```mermaid
sankey-beta
  浏览器,Java 请求：conversationId、content、attachmentIds、capabilityRef、Authorization,1
  Java 请求,Java ACL：tenantId、userId、conversationId、fileId、capabilityRef,1
  Java ACL,Java 业务库：conversation、messageId、runId、runtimeMode、status、lastSequence,0.9
  Java ACL,Run JWT：iss、aud、sub、tenant、runId、businessSessionId、capabilityRef、scope、jti、iat、exp,0.8
  Java ACL,agent-run-v1：runId、businessSessionId、capabilityRef、input.text、fileRefs、contextSummary、runtime.mode、runtime.sessionRef,0.8
  Java ACL,credentials：platformBearer（仅需鉴权能力）,0.25
  Run JWT,Python 验证：签名、claims、请求绑定、jti,0.8
  agent-run-v1,Python Profile：runtimeMode、workflowRef、skillRefs、mcpRefs、权限策略,0.8
  Python Profile,QueryExecutor：runId、prompt、resume、workspace、mcpConfig,0.45
  Python Profile,SessionManager：sessionKey、runId、sessionRef,0.35
  SessionManager,SessionActor 消息队列：runId、text、fileRefs,0.35
  SessionManager,SessionActor 控制队列：runId、interrupt、cancel,0.12
  SessionActor 消息队列,ClaudeSDKClient：connect、query、receive-response,0.35
  SessionActor 控制队列,ClaudeSDKClient：interrupt,0.12
  QueryExecutor,Claude Session：runtimeSessionRef、transcript,0.45
  ClaudeSDKClient,Claude Session：runtimeSessionRef、transcript,0.35
  Claude SDK,ObservationRecorder：SDK消息、流式事件、thinking、工具调用、工具结果、ResultMessage,0.75
  ObservationRecorder,私有观测 Journal：observationId、observationSequence、runId、traceId、privatePayload,0.75
  ObservationRecorder,公共事件翻译：phase、textDelta、tool状态、终态,0.75
  私有观测 Journal,观测 Collector：加密详细观测、受限索引、补传,0.65
  credentials,Python MCP 注入：MCP-AUTH-RULES、header、env,0.25
  Python MCP 注入,MCP：当前 Run 或 Client 连接的临时凭据,0.25
  Java ACL,File Broker：fileRef、runId、tenant、user、expiresAt,0.3
  File Broker,Workspace：input、work、output,0.3
  Claude Session,agent-events-v1：runId、sequence、type、phase、textDelta、artifactRef、status,0.75
  agent-events-v1,Event Store：runId、sequence、publicPayload、occurredAt,0.75
  Event Store,Java 统一 SSE：Last-Event-ID、afterSequence、脱敏事件,0.75
  Java 统一 SSE,浏览器重连：runId、sequence、phase、tool状态、正文、artifactRef,0.75
  Workspace,对象存储：artifactRef、storageKey、mimeType、status,0.25
  对象存储,Java 下载 ACL：artifactRef、tenantId、ownerId、expiresAt,0.25
```

图中数值只用于表现流向，不表示真实流量。`platformBearer` 只沿 Java -> Python MCP 注入 -> 指定 MCP 流动；`runtimeSessionRef` 只用于恢复 Claude 历史；浏览器只看到 `runId`、公共事件序号、阶段、工具状态、正文和授权后的 Artifact。thinking 原文、工具名称、参数、结果和 SDK 原始消息只沿 ObservationRecorder -> 私有观测 Journal/Collector 流动，不进入 Java 统一 SSE。
