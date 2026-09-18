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
  "payload": {},
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
| `capabilityRef` | 否 | 普通会话省略或null，内部归一为conversation；选择能力时传稳定业务标识，空字符串拒绝。 |
| `input.text` | 条件必填 | 文本输入；与附件、payload 至少一个非空，最长 1,000,000 字符；input 对象仍必填。 |
| `payload` | 否 | 当前仅撰写能力选择预制模板时传templateKey；其他场景省略或{}，不得自行增加字段；参与Run幂等比较。 |
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

创建、查询、控制和取消共用同一 Run 响应：`runId: string` 为执行标识，`status: string` 为执行状态，`lastSequence: integer` 为事件续传游标；失败时可带 `error: string` 稳定错误码。身份和SDK执行信息不进入响应；会话执行检索另返回messageId及capabilityRef等公开关联字段，见4.3。

### 3.2 Capability 字段

创建Run可省略capabilityRef进行普通会话；选择能力仅作用于当前消息。同一businessSessionId保留业务连续性，各能力使用隔离Client，跨能力摘要须由Java作为已授权输入提供。目录返回全部登记能力，不代表用户授权或模型/MCP健康检查。当前值为：

| `capabilityRef` | Python 内部映射 | 附件 |
| --- | --- | --- |
| `conversation` | 无 Workflow，使用通用对话配置 | 支持 |
| `document-writing` | `writing-docx` | 支持 |
| `national-excellence-data-qa` | `double-high-qa` | 不支持 |

Java 只传业务标识；映射表、Workflow、Skill、MCP 和运行模式由 Python 维护。

### 3.3 查询能力目录

```http
GET /internal/v1/capabilities
```

无请求正文和分页参数。成功返回 200，字段为 `capabilityRef`（执行标识）、`name`（默认名称）、`description`（用途）、`supportsAttachments`（是否支持附件）：

```json
{"capabilities":[
  {"capabilityRef":"conversation","name":"通用对话","description":"日常交流、内容总结与问题解答","supportsAttachments":true},
  {"capabilityRef":"document-writing","name":"文档撰写","description":"起草、修改与生成 Word 文档","supportsAttachments":true},
  {"capabilityRef":"national-excellence-data-qa","name":"双高问数","description":"查询国双高项目、任务、资金与绩效","supportsAttachments":false}
]}
```

目录接口无需鉴权，不要求 Authorization 请求头，也不依赖 Runtime JWT 密钥配置。仅返回公开能力描述；Java 按业务权限筛选并配置展示后再提供给前端。创建、查询和控制 Run 仍须通过 Run JWT 鉴权。

### 3.4 业务 payload

`payload`只传已约定的能力参数，当前唯一字段为document-writing的templateKey，当前登记值为szpt-midterm；其他场景省略或传`{}`。标题、年份及要求放input.text，文件走input.attachmentRefs；接入方不得自行新增字段或编造模板标识。顶层必须为对象，input对象始终必填。完整接入示例见[HTML的payload章节](../python-api.html#business-payload)。

实现边界：当前通用JSON校验仍可能接受未约定字段并将其附加到模型输入，尚无逐能力字段白名单；这不构成对自定义参数的支持。现有通用上限为Python重新序列化后的UTF-8 JSON 64 KiB、根记0层后任意值深度最多16。本次仅修正文档约定，不改变运行时校验行为。

`document-writing` 能力可使用已登记的预制模板：

```json
{"capabilityRef":"document-writing","input":{"text":"生成截至2025年底的双高中期自评报告"},"payload":{"templateKey":"szpt-midterm"}}
```

使用预制模板时，`payload.templateKey`须是非空字符串，满足Python部署内的模板登记、启用状态、能力绑定和指南路径校验；当前省略或null均不选模板，其他能力传非null值也会触发模板及能力校验。运行时冻结实际DOCX与指南版本，位置地图及取数计划不参与启动校验。它不是路径、数据库名、版本或权限参数。年份、截止日期及写作要求放在`input.text`，外部材料用`input.attachmentRefs`。当前`szpt-midterm`按可信配置绑定`schoolDoubleHigh`及`hpm`查询，Java不传连接、SQL、路径或密码。模板校验在异步执行准备阶段，未知、停用、未授权等可在创建返回202后使Run进入failed；接收请求不等于模板校验通过。

`national-excellence-data-qa` 不需要专属 payload 字段；问题、年份和范围要求放在 `input.text`，数据源、查询规范和身份范围由 Runtime 的可信资产及工具策略装配。

自定义模板保存在Java时，使用`document-writing`且不传`templateKey`；通过`input.attachmentRefs`提交模板文件引用，在`input.text`明确哪份文件是模板及写作要求。Python经File Broker获取文件后走普通撰写分支：读取结构、按需收集事实、撰写并生成新DOCX，不自动注册预制模板。当前`purpose`仅支持`input`和`reference`，没有`template`值；再次使用文件仍须提交引用。数据库工具须已配置且获准，上传文件不改变数据权限。若同时传入`templateKey`和附件，仍绑定该预制模板，附件不会覆盖模板选择。

```json
{"protocol":"agent-run/v1","runId":"run_custom_01","messageId":"message_custom_01","capabilityRef":"document-writing","input":{"text":"以附件《自评报告模板.docx》为模板，保留章节和表格，结合可用数据撰写2025年度报告；证据不足时写有限结论和具体缺口，无证据时按原主题写分析框架、数据需求及后续动作，不确定内容用黄色字体，不留空。","attachmentRefs":[{"fileId":"file_template_01","purpose":"input"}]}}
```

以上为已有附件和普通撰写入口，不代表任意自定义模板的保真编辑与自动取数质量已验收。

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

### 4.3 按业务会话查询执行记录

`GET /internal/v1/sessions/{businessSessionId}/runs?limit=50&cursor=...`

Java先校验用户对该业务会话的读取权限，再签发`scope: session.read`的短期JWT。必须包含`iss`、`aud`、`iat`、`exp`、`jti`、`tenant`、`sub`、`businessSessionId`，后者必须与路径相同；不要求runId或capabilityRef。使用相同Runtime签名配置，只读请求不消耗jti。普通run.read/run.execute权限不能访问此接口；session.read也不授予单Run读取、取消或执行权限。

返回`{"runs":[{"runId":"run_01","messageId":"message_01","capabilityRef":"conversation","status":"succeeded","createdAt":1725400000000,"updatedAt":1725400001000}],"nextCursor":null}`。时间为Unix毫秒，历史记录缺少messageId时为null；不返回身份、消息正文、内部metadata或SDK会话引用。

- 查询始终按JWT的tenant、sub及路径会话过滤，跨能力汇总；无记录返回200和空数组，不能据此判断Java业务会话是否存在。
- limit默认50，范围1–100。按createdAt、runId倒序稳定排序；首次省略cursor，下页原样传回nextCursor，null表示结束。不要解析游标或把它当授权凭据。
- 翻页使用固定的创建时间和Run ID位置，不受状态更新或已翻过位置之前的新记录影响；不是数据库快照，刷新首页才能看到最新记录。游标定位不到当前授权会话的记录时返回400，重新从首页查询。
- 无效/跨范围游标返回400；分页参数类型、范围或长度错误返回422；JWT无效返回401，密钥未配置返回503。响应禁止缓存。

会话标题、消息和会话列表仍由Java维护，Python仅查询现有RunStore，不接入SessionStore或新增业务会话表。

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
| `message.delta` | `textDelta` | 本次新收到的一小段回答，加在已有回答末尾；按事件sequence顺序处理，重复序号不重复添加。 |
| `tool.started` | `toolCallId`、`toolName`、`status: started` | 展示工具调用开始。 |
| `tool.progress` | `toolCallId`、`toolName`、`status: running` | 展示工具仍在执行。 |
| `tool.finished` | `toolCallId`、`toolName`、`status: finished`、`isError` | 展示工具完成或失败。 |
| `artifact.pending / uploading / ready / failed / unknown` | 本节Artifact文件对象 | Runtime上传状态，ready才包含远端fileId；与模型正文无关。 |
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
| `saving_files` | 无 | SDK已结束，等待已提交文件上传收尾，Run仍为running。 |

文件逐个下载，进度属于当前 fileId，不是整个 Run 的完成百分比。准备授权时显示不定进度；大小为 0 时不做除法。SSE 示例：

```text
id: 4
event: phase
data: {"protocolVersion":"agent-events/v1","runId":"run_01","sequence":4,"type":"phase","payload":{"name":"downloading_file","fileId":"file_01","receivedBytes":26214400,"totalBytes":109051904}}
```

所有准备阶段通过同一 RunStore 保存并按序回放；断开 SSE 不取消下载。停止生成使用 control 的 `option: cancel`，取消下载并清理本次临时输入，不删除 Java 原文件。文件流不通过 SSE 传输。

## 6. Artifact 模块

发布工具生成不可变artifactId，父Runtime按可信Run登记快照，并自动向部署配置fileService上传。模型不提供上传地址或业务身份，工具pending不代表上传成功。同名再次发布产生新ID，各Run列表互不混用。

| GET 路径 | 响应 |
| --- | --- |
| `/internal/v1/runs/{runId}/artifacts` | `{"files": [...]}`，仅本Run已登记文件，无查询参数 |
| `/internal/v1/runs/{runId}/artifacts/{artifactId}` | `{"file": {...}}`，单文件状态 |
| `/internal/v1/runs/{runId}/artifacts/{artifactId}/content` | 本地快照二进制，用于Java鉴权代理、核验或人工恢复 |

均使用run.read或run.execute的Run JWT，不消耗jti，禁止缓存。文件对象包含artifactId/name/size/suffix/status；仅ready包含fileId（上传响应data.id），failed/unknown包含稳定error。列表无成果返回空数组；旧?name定位返回400，JWT无效401，密钥未配置503，不存在或跨Run文件404。内容接口可读取failed/unknown的本地快照，不证明远端ready。

状态为pending→uploading→ready/failed/unknown；发送前配置失败可直接failed。超时、无效成功响应、服务端5xx或上传中断可能已经产生远端文件，记unknown，不自动重试；本版没有重试API。重启仅恢复pending，原uploading标为unknown，不代表恢复SDK执行。状态与事件同事务持久化，SSE分页回放；终态Run事件等已登记上传全部收尾后发送。run.completed代表SDK成功，不保证文件ready，取消不撤销已提交上传。

Java按已保存的runId/messageId及artifactId更新文件卡片，ready后关联fileId、校验业务下载ACL；不解析回答链接。data.url是内部存储路径，不公开也不推测下载URL。上传服务未提供租户授权/幂等对账，Java和前端仍需接入。完整格式化JSON、错误码与fileService配置见[API HTML](../python-api.html#artifacts)，决策见[ADR-030](../ADR/030-runtime-artifact-delivery.md)。

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

必需Claim：`iss`、`aud`、`iat`、`exp`、`jti`、`sub`、`tenant`、`runId`、`capabilityRef`、`scope`。正文省略或null能力时，JWT仍绑定conversation；不能省略授权Claim。创建时另须绑定messageId，使用业务会话时绑定businessSessionId。

scope 与接口的关系：

| 接口 | 允许 scope | `jti` 防重放 |
| --- | --- | --- |
| 创建 Run | `run.execute` | 是 |
| 查询 Run、SSE、Artifact | `run.read` 或 `run.execute` | 否 |
| 控制/取消 | `run.control` 或 `run.cancel` | 是 |
| 按业务会话列出Run | `session.read`，绑定tenant、sub及businessSessionId | 否 |

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
| `422` | 查询参数校验失败，返回 JSON detail；其他业务错误通常为 text/plain |
| `503` | Runtime JWT 或 File Broker 配置不可用 |

File Broker 的文件不可用、无权或已过期会转换为 Run 的 `run.failed`，使用稳定错误码，例如 `file_access_denied`、`file_access_expired`、`file_broker_unavailable`、`file_validation_failed`。
