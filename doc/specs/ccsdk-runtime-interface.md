# CCSDK Runtime 协议规范

## 变更规则

1. 本文件是 Java 与 Python Runtime 的接口契约；字段名、路径、状态和事件语义以此为准。
2. 修改前先确认所属模块和影响范围。任何字段、路径、鉴权规则、File Broker 头或事件变化，都必须同步更新 `doc/specs/java-control-plane.md`、`doc/python-api.html` 和协议测试；SDK 内部边界以 `ARCHITECTURE.md` 和源码为准。
3. 请求和响应示例必须能按当前代码解析。接口文档只描述已实现内容，不写规划、兼容层或未实现接口。
4. 本地自测由独立 ScribePlayground 模拟 Java，包含测试 JWT 和 HTTPS File Broker，不得为了自测修改本协议或在 Runtime 加入测试身份分支。

## 1. 模块地图

| 模块 | 实现入口 | 作用 | Java 可见内容 |
| --- | --- | --- | --- |
| HTTP Runtime | `python/server.py` | 创建、查询、订阅、控制 Run | `/internal/v1/runs/**` |
| 请求协议 | `python/runtime/protocol.py` | 校验 `agent-run/v1` 请求和字段 | Run 请求 JSON |
| 鉴权 | `python/runtime/auth.py`、`python/server.py` | 校验 JWT、scope、请求绑定和防重放 | `Authorization` 请求头 |
| Capability | `python/runtime/capabilities.py`、`python/server.py` | 查询已登记能力；将业务标识映射到内部执行配置 | `GET /internal/v1/capabilities`、Run 字段 `capabilityRef` |
| 执行与事件 | `python/runtime/claude_sdk.py`、`agent_worker.py`、`session_actor.py` | 调用 Claude Agent SDK、维护 Provider Session、转换公共事件 | SSE 事件 |
| Run 存储 | `python/runtime/run_store.py` | 保存 Run 摘要和有序事件，支持幂等与续传 | Run 查询、SSE |
| 输入文件 | `python/runtime/file_broker.py` | 从 Java File Broker 获取附件并校验后写入 workspace | File Broker 请求/响应 |
| 交付物 | `python/server.py`、`python/tools/artifacts.py` | 列出和下载 Run 生成的文件 | Artifact 接口 |

Java 只提交业务字段。Workflow、Skill、MCP、模型、工作目录、工具参数和 Provider Session 都由 Python 内部决定。

## 2. 通用约定

- Runtime Base URL 由部署配置提供；以下路径相对于该地址。
- JSON 使用 UTF-8 和 `application/json`；事件使用 `text/event-stream`。
- ID 使用字母、数字、`_`、`-`，长度不超过 256；`runId` 由 Java 在请求前生成，作为幂等、查询和控制标识。SDK 的 `session_id` 在 Python 内部关联，不替代 `runId`。
- Run 状态：`queued`、`running`、`waiting`、`succeeded`、`failed`、`cancelled`。
- `businessSessionId` 是业务会话关联键；Python 依据它维护内部 Provider Session，但两者不是同一个 ID。

## 3. Run 请求模块

### 3.1 创建或幂等重提交

```http
POST /internal/v1/runs
Authorization: Bearer <Run JWT>
Content-Type: application/json
```

输入：

```json
{
  "protocol": "agent-run/v1",
  "runId": "run_01",
  "messageId": "message_01",
  "businessSessionId": "session_01",
  "capabilityRef": "document-writing",
  "payload": {"reportTitle": "年度工作报告", "year": 2026},
  "input": {
    "text": "请整理这个文档",
    "attachmentRefs": [
      {"fileId": "file_01", "purpose": "input"}
    ]
  },
  "credentials": {
    "platformBearer": "业务 Token"
  }
}
```

字段：

| 字段 | 必填 | 设计原因与约束 |
| --- | --- | --- |
| `protocol` | 是 | 固定为 `agent-run/v1`，用于拒绝其他请求形状。 |
| `runId` | 是 | 幂等和恢复执行；同一 ID 的非同形请求会被拒绝。 |
| `messageId` | 是 | 关联 Java 业务消息，不作为 Provider 会话 ID。 |
| `businessSessionId` | 否 | 关联连续业务会话；不传则按无业务会话执行。 |
| `capabilityRef` | 是 | 稳定的业务入口；由 Python 映射到内部 Workflow/Skill/MCP。 |
| `input.text` | 条件必填 | 文本输入；与附件、payload 至少一个非空，最长 1,000,000 字符；input 对象仍必填。 |
| `payload` | 否 | 业务 JSON 对象，默认空；作为本次用户业务数据追加到模型输入，参与 Run 幂等比较。 |
| `input.attachmentRefs` | 条件必填 | 固定文件引用，最多 64 项；`purpose` 为 `input` 或 `reference`。 |
| `credentials.platformBearer` | 否 | 仅按 Python 的 MCP 规则注入指定业务服务；不写入 Prompt、事件或 Run 存储。 |

成功返回新 Run 为 `202`，同一请求幂等重提交为 `200`：

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

创建、查询、控制和取消共用同一 Run 响应：`runId: string` 为执行标识，`status: string` 为执行状态，`lastSequence: integer` 为事件续传游标；失败时可带 `error: string` 稳定错误码。身份、业务关联和 SDK 执行信息只保存在 Python 内部，不进入响应。

### 3.2 Capability 字段

创建 Run 使用 `capabilityRef` 选择能力。目录接口返回当前登记的全部 SDK 能力，不代表用户已获得业务授权，也不是模型/MCP 健康检查。当前已实现值为：

| `capabilityRef` | Python 内部映射 | 附件 |
| --- | --- | --- |
| `conversation` | 无 Workflow，使用通用对话配置 | 支持 |
| `document-writing` | `writing-docx` | 支持 |
| `national-excellence-data-qa` | `database-qa` | 不支持 |

Java 只传业务标识；映射表、Workflow、Skill、MCP 和运行模式由 Python 维护。

### 3.3 查询能力目录

```http
GET /internal/v1/capabilities
Authorization: Bearer <Catalog JWT>
```

无请求正文和分页参数。成功返回 200，字段为 `capabilityRef`（执行标识）、`name`（默认名称）、`description`（用途）、`supportsAttachments`（是否支持附件）：

```json
{"capabilities":[
  {"capabilityRef":"conversation","name":"通用对话","description":"日常交流、内容总结与问题解答","supportsAttachments":true},
  {"capabilityRef":"document-writing","name":"文档撰写","description":"起草、修改与生成 Word 文档","supportsAttachments":true},
  {"capabilityRef":"national-excellence-data-qa","name":"双高问数","description":"查询国双高项目、任务、资金与绩效","supportsAttachments":false}
]}
```

Catalog JWT 复用 Run JWT 的 HS256 密钥、issuer、audience 和有效期校验。必需 Claim 为 `iss`、`aud`、`iat`、`exp`、`jti`、`sub`、`scope`；`sub` 是 Java 服务身份，`scope` 为 `capability.read`。不要求 tenant、runId、capabilityRef；读取不消费 jti。鉴权失败返回 401，密钥未配置返回 503。Java 按业务权限筛选并配置展示后再提供给前端。

### 3.4 业务 payload

`payload` 支持嵌套对象、数组、字符串、有限数值、布尔值、null；序列化后的 UTF-8 JSON 最多 64 KiB，嵌套深度最多 16 层。当前按业务数据传给模型理解，不作为运行配置合并，不自动下载其中的 fileId，也不保证模型完成确定性字段校验。

不得放 Token、密钥、身份、文件二进制或执行配置。任意层级的以下字段名会被拒绝（忽略大小写、下划线和连字符）：`credentials`、`platformBearer`、`authorization`、`token`、`apiKey`、`secret`、`tenantId`、`userId`、`workflowRef`、`skill`、`skills`、`agent`、`agents`、`model`、`tools`、`mcp`、`mcpServers`、`mcps`、`cwd`、`workspace`、`permissions`。业务数据会进入模型上下文，字段过滤不能识别所有秘密内容，Java 必须只传允许模型读取的数据。

附件仍通过 `input.attachmentRefs` 显式授权，凭据仍通过 `credentials.platformBearer` 传递。相同 runId 修改 payload 返回 409；不在 Run 响应中回传 payload。

## 4. Run 查询与控制模块

### 4.1 查询 Run

```http
GET /internal/v1/runs/{runId}
Authorization: Bearer <Run JWT>
```

返回：`{"run":{"runId":"run_01","status":"running","lastSequence":3}}`。字段与创建响应相同；失败时可带 `error`。

### 4.2 控制 Run

```http
POST /internal/v1/runs/{runId}/control
Authorization: Bearer <Run JWT>
Content-Type: application/json
```

输入：`{"option":"cancel"}` 或 `{"option":"interrupt"}`。`option` 为必填字符串，不接受其他字段。

| option | 执行效果与状态 |
| --- | --- |
| `interrupt` | 请求中断当前模型响应，不是暂停/恢复。文件准备期间等同取消准备，进入 cancelled；模型执行期间持久 Client 调用 SDK interrupt，终态由随后 SDK 结果决定；独立执行停止任务并进入 cancelled。没有活动任务时不改变状态。 |
| `cancel` | 取消本次 Run，包括排队执行；执行取消后进入 cancelled 并产生 run.cancelled 事件。业务前端“停止生成”使用此值。 |

两者都不删除业务会话或已有输出，不撤销工具已完成的操作；已结束的 Run 保持原状态。返回当前 Run，例如 `{"run":{"runId":"run_01","status":"cancelled","lastSequence":8}}`；执行可能仍在收尾，最终状态以 SSE 终态事件或后续查询为准。继续对话应创建新 Run。

快捷接口 `POST /internal/v1/runs/{runId}/cancel` 等价于 control 的 `{"option":"cancel"}`。

## 5. SSE 事件模块

```http
GET /internal/v1/runs/{runId}/events?afterSequence=0
Authorization: Bearer <Run JWT>
Accept: text/event-stream
```

事件支持 `afterSequence` 或 `Last-Event-ID` 续传，查询参数优先。首次从 0 读取；已成功处理到事件 7 时传 7，只补取序号大于 7 的事件。`lastSequence` 是服务端已保存的最大序号（0 表示尚无事件），不能代替消费端已处理的游标，否则会跳过未消费事件。这是事件回放，不重启执行，也不是 SDK Session resume。每帧包含 `id`、`event` 和 JSON `data`：

```text
id: 4
event: message.delta
data: {"protocolVersion":"agent-events/v1","runId":"run_01","sequence":4,"type":"message.delta","payload":{"textDelta":"回复片段"}}
```

公共事件：

| `type` | `payload` | 设计原因 |
| --- | --- | --- |
| `run.started` | `status: "running"` | 明确 Run 已进入执行。 |
| `phase` | `name` 为下表准备阶段或 `started\|thinking\|response\|working`；思考阶段另有 `visible:true` | 展示准备与执行进度，不暴露思考正文。 |
| `message.delta` | `textDelta` | 传输助手回复增量，客户端按顺序拼接。 |
| `tool.started` | `toolCallId`、`toolName`、`status: started` | 展示工具调用开始。 |
| `tool.progress` | `toolCallId`、`toolName`、`status: running` | 展示工具仍在执行。 |
| `tool.finished` | `toolCallId`、`toolName`、`status: finished`、`isError` | 展示工具完成或失败。 |
| `run.completed` | `inputTokens`、`outputTokens`、`turns`（可选） | 表示执行成功并提供统计。 |
| `run.failed` | `code`，可带统计 | 表示执行失败；使用稳定错误码。 |
| `run.cancelled` | 空对象 | 表示执行被取消。 |

公共事件不包含工具参数、工具结果正文、Prompt、文件路径、凭据或供应商原始消息。每个 Run 的 `sequence` 从 1 递增，RunStore 负责持久化和回放。

### 5.1 文件准备阶段

创建 Run 立即返回 202；后台顺序执行文件准备和模型查询。`running` 包含准备和执行，`run.started` 不代表模型已启动。无附件跳过全部文件阶段，文件准备失败或取消时不启动模型。

| phase.name | 额外字段 | 含义 |
| --- | --- | --- |
| `queued` | 无 | 持久 Client 等待当前会话可执行。 |
| `preparing_files` | `fileCount` | 开始准备本次附件。 |
| `preparing_file` | `fileId` | 正在向 Java 请求该文件，大小尚未确定。 |
| `downloading_file` | `fileId`、`receivedBytes`、`totalBytes` | 当前文件已接收字节及授权总大小；开始时 receivedBytes 为 0，中间更新最多每 500ms 一次，结束时补发最终字节数。 |
| `validating_file` | 同上 | 字节传输完毕，正在完成落盘和大小、SHA-256 校验；不等于模板内容解析成功。 |
| `file_ready` | 同上 | 当前文件校验成功。 |
| `files_ready` | `fileCount` | 全部附件就绪。 |
| `model_starting` | 无 | 已结束输入准备，进入 SDK 执行阶段；不是模型思考事件。 |

文件逐个下载，进度属于当前 fileId，不是整个 Run 的完成百分比。准备授权时显示不定进度；大小为 0 时不做除法。SSE 示例：

```text
id: 4
event: phase
data: {"protocolVersion":"agent-events/v1","runId":"run_01","sequence":4,"type":"phase","payload":{"name":"downloading_file","fileId":"file_01","receivedBytes":26214400,"totalBytes":109051904}}
```

所有准备阶段通过同一 RunStore 保存并按序回放；断开 SSE 不取消下载。停止生成使用 control 的 `option: cancel`，取消下载并清理本次临时输入，不删除 Java 原文件。文件流不通过 SSE 传输。

## 6. Artifact 模块

### 6.1 列出交付物

```http
GET /internal/v1/runs/{runId}/artifacts
Authorization: Bearer <Run JWT>
```

返回：`{"files":[{"name":"result.docx","size":24576}]}`。

### 6.2 下载交付物

```http
GET /internal/v1/runs/{runId}/artifacts?name=result.docx
Authorization: Bearer <Run JWT>
```

返回文件二进制，并设置 `Content-Type`、`Content-Disposition` 和 `Cache-Control: no-store`。`name` 只能定位该 Run 关联的交付物目录；独立执行使用 Run 目录，持久会话执行共享会话目录，因此列表可能包含同一会话之前生成的文件。

## 7. 鉴权模块

所有 `/internal/v1/runs/**` 接口（包括查询、SSE、Artifact、控制和取消）都必须发送 `Authorization: Bearer <Run JWT>`。JWT 由 Java 签发，Python 校验；不是省略鉴权，也不在 JSON 正文中重复放 Token。幂等重试保持原 `runId` 和业务请求，使用新 `jti` 签发 JWT。

### 7.1 密钥和配置

Python 使用 `python/runtime/auth.py` 的 HS256 实现：对 `base64url(header) + "." + base64url(claims)` 使用 HMAC-SHA256 签名。Java 与 Python 必须通过部署密钥管理共享同一个非空 `CCSDK_RUNTIME_JWT_SECRET`；该值只存在于服务端环境或 Secret Manager，不进入浏览器、代码库、日志和请求正文。配置名：

```text
CCSDK_RUNTIME_JWT_SECRET=<Java 与 Python 共享的随机密钥>
CCSDK_RUNTIME_JWT_AUDIENCE=ccsdk-runtime
CCSDK_RUNTIME_JWT_ISSUER=string-ai-center-service
```

JWT 头固定为 `{"alg":"HS256","typ":"JWT"}`。Java 的 `aud`、`iss` 必须与 Python 当前配置一致。

### 7.2 JWT 输入

Java 对每次 Runtime 请求生成短期 JWT。必须包含：

```json
{
  "iss": "string-ai-center-service",
  "aud": "ccsdk-runtime",
  "iat": 1725400000,
  "exp": 1725400600,
  "jti": "jti_01",
  "sub": "user_01",
  "tenant": "tenant_01",
  "runId": "run_01",
  "capabilityRef": "document-writing",
  "businessSessionId": "session_01",
  "messageId": "message_01",
  "scope": "run.execute"
}
```

必需 Claim：`iss`、`aud`、`iat`、`exp`、`jti`、`sub`、`tenant`、`runId`、`capabilityRef`、`scope`。创建时还必须包含与请求一致的 `messageId`；使用业务会话时包含与请求一致的 `businessSessionId`。

scope 与接口的关系：

| 接口 | 允许 scope | `jti` 防重放 |
| --- | --- | --- |
| 创建 Run | `run.execute` | 是 |
| 查询 Run、SSE、Artifact | `run.read` 或 `run.execute` | 否 |
| 控制/取消 | `run.control` 或 `run.cancel` | 是 |

### 7.3 Python 校验和输出

Python 校验 JWT 格式、HS256 签名、`aud`、`iss`、`iat`/`exp`、`jti`、身份 Claim 和 scope。创建时绑定请求中的 `runId`、`capabilityRef`、`businessSessionId`、`messageId` ；身份仅从已验证 JWT 的 `tenant`、`sub` 获取并保存为内部归属。查询、SSE、Artifact、控制和取消按已保存 Run 校验 `runId`、`capabilityRef`、业务会话和身份，不再校验 `messageId`。失败返回纯文本错误，状态为 `401`；未配置 JWT 密钥时，Artifact 返回 `401`，其余 Run 接口返回 `503`。

`credentials.platformBearer` 是下游业务 Token，不是 Runtime 鉴权 Token。它只在当前执行内按受信 MCP 规则使用，Python 不从中推导身份或权限。

## 8. File Broker 模块

### 8.1 Python 请求 Java

Java 接收上传并分配 fileId；本次 Run 的 `input.attachmentRefs` 是 Python 获取文件的唯一显式入口。Python 执行前预取这些引用，不解析文本或 payload 中的 fileId。再次使用历史文件需重新提交引用。生成的 Artifact 由 Java 下载、登记为业务文件后，才能用新 fileId 再次提交。

当 Run 含 `input.attachmentRefs` 时，Python 向 `CCSDK_FILE_BROKER_URL` 发起：

```http
POST <CCSDK_FILE_BROKER_URL>
Authorization: Bearer <Run JWT 或 File Broker 服务 Token>
Accept: application/json, application/octet-stream
Content-Type: application/json
```

请求体：`{"runId":"run_01","fileId":"file_01","purpose":"input"}`。

Java 必须按 `runId`、当前调用身份、业务会话和 `fileId` 校验访问权限。Python 默认转发本次 Run JWT；当 `CCSDK_FILE_BROKER_AUTH_MODE=service` 时改用 `CCSDK_FILE_BROKER_SERVICE_TOKEN`。两种模式不混用。

### 8.2 Java 返回一次性 URL

```json
{
  "fileId":"file_01",
  "name":"source.docx",
  "mimeType":"application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  "size":1024,
  "sha256":"0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
  "downloadUrl":"https://files.example.com/one-time/file_01",
  "expiresAt":1725400300000,
  "oneTime":true
}
```

`fileId` 必须与请求一致；`name`、`mimeType`、`size`、`sha256` 是完整性校验所需字段。`downloadUrl` 必须是 HTTPS、短时、一次性地址；Python 不跟随重定向，也不会向该下载地址转发 Run JWT。

### 8.3 Java 返回代理流

响应为原始文件字节，并包含：

```text
X-File-Id: file_01
X-File-Name: source.docx
X-File-Mime-Type: application/octet-stream
X-File-Size: 1024
X-File-Sha256: 0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef
```

Python 按最多 256 KiB 的块写入临时文件并计算 SHA-256；校验大小与摘要成功后原子移动到可用路径，全部附件就绪后才查询模型。取消或失败删除临时下载；完成 Run 后清理临时输入。文件传输成功不代表 DOC/DOCX 内容可由具体工具解析。URL 模式还必须配置 `CCSDK_FILE_BROKER_ALLOWED_HOSTS`。

### 8.4 大文件与超时

| 服务端配置 | 默认值 | 范围 |
| --- | --- | --- |
| `CCSDK_FILE_MAX_BYTES` | 268435456（256 MiB） | 单文件大小上限；不是磁盘总配额。 |
| `CCSDK_FILE_PREPARE_TIMEOUT_MS` | 600000（10 分钟） | 本 Run 全部附件获取和校验预算，从开始获取计时。 |
| `CCSDK_FILE_BROKER_TIMEOUT_MS` | 15000（15 秒） | HTTP 连接、等待数据等单次网络操作超时，不是整个下载耗时。 |
| `CCSDK_RUN_EXECUTION_TIMEOUT_MS` | 300000（5 分钟） | 输入准备完成后单独计算的 SDK 执行预算。 |
| `CCSDK_CLIENT_QUEUE_TIMEOUT_MS` | 300000（5 分钟） | 持久 Client 等待执行的排队预算，不占文件准备及执行预算。 |

文件准备超时返回 `run.failed` / `file_broker_timeout`；排队超时为 `run_queue_timeout`；模型执行超时 Query 为 `timeout`，Client 为 `sdk_timeout`。均为异步 SSE 错误，并可查询 Run.error；不是创建 HTTP 请求等待这些阶段完成。

## 9. 错误响应

Runtime 错误为 `text/plain`，常见状态：

| HTTP | 含义 |
| --- | --- |
| `400` | JSON、字段、Capability、附件或 control 操作无效 |
| `401` | Run JWT 缺失、签名/绑定/scope 校验失败 |
| `404` | Run 或 Artifact 不存在 |
| `409` | 幂等请求的归属/请求不一致，或状态冲突 |
| `421` | Host 不允许 |
| `503` | Runtime JWT 或 File Broker 配置不可用 |

File Broker 的文件不可用、无权或已过期会转换为 Run 的 `run.failed`，使用稳定错误码，例如 `file_access_denied`、`file_access_expired`、`file_broker_unavailable`、`file_validation_failed`。
