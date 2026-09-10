# Java 控制面：推荐设计与当前实现

更新时间：2026-09-10。本次只整理文档，不修改接口或业务代码。
结论：Python 已提供 Run、鉴权、SSE 和文件接口；本地 Java 有接入骨架，但请求仍是旧协议，不能视为已经联通。

## 0. 维护约定与核对范围

更新条件与同步范围见[文档职责表](../README.md)。第 1 部分是推荐设计；第 2 部分的实现结论须有源码依据，未做真实联调不得标为联通。
接口按方向/路径、鉴权、输入、输出、字段、限制描述，共用字段只解释一次；保留必要表格和代表性报文。
修改时更新顶部日期；源码核对基线与验证范围按实际检查记录，不因文字调整宣称重新完成全量核对。

本次核对基线如下；含未提交修改的快照不等于该提交本身。

| 范围 | 基线与阅读入口 |
| --- | --- |
| Python | 本仓库 `51a8e67`；[server.py](../../python/server.py)、[protocol.py](../../python/runtime/protocol.py)、[auth.py](../../python/runtime/auth.py)、[file_broker.py](../../python/runtime/file_broker.py)、[capabilities.py](../../python/runtime/capabilities.py)；并核对 config、SDK Facade、Worker、Actor、RunStore 和测试。 |
| Java | `D:/code/string-ai-center-service/src/main/java/com/string/ai`；HEAD `3761748` 加本地未提交改动。核对 controller/chat、service/chat、service/runtime、service/dify、service/agent、support、DTO 和配置。 |
| 前端 | `D:/code/string-ai-center-web/src`；HEAD `96fc1de` 加本地未提交改动。核对 api/chat、shared/ai、views/ai 的调用、SSE、消息、附件、模板组件及框架 getHeaders。 |

## 1. 推荐设计（非强制接口）

### 1.1 分层与适配

建议链路：`前端 -> Java 会话/消息/ACL -> 执行适配器 -> Python 或 Dify -> Java 公共事件 -> 前端`。

| 层级 | 职责与建议 | 理由 |
| --- | --- | --- |
| Java 业务层 | 管理 Agent、业务会话/消息、文件 ACL、可用 Capability 和执行记录；按服务端配置选择执行后端。 | 前端选择业务能力，不能决定模型、Workflow 或 MCP。 |
| Java 适配层 | 沿用 AgentRuntimeAdapter，收敛启动、查询、订阅、取消；Python/Dify 各自翻译报文和文件引用，向上提供同一业务事件。 | 现有 Dify 仍直接耦合 ChatService；建议归入相同边界，接口名不强制。 |
| Python | 将 capabilityRef 映射到 Workflow，装配 Skill/MCP，维护模型、SDK Session 和 Query/Client 生命周期。 | Java 不承担 Agent 调度策略；Capability 不重复配置 Workflow 已声明的 Skill。 |
| 前端 | 保留会话列表、消息气泡、附件/模板选择、停止、重新生成和文件预览；增加独立阶段与工具状态。 | 文件准备、思考、工具执行和回答是不同状态。 |

Agent 推荐只维护展示信息、`allowedCapabilityRefs` 和 `defaultCapabilityRef`；Java 用当前用户权限与 Agent 允许能力取交集。Python 目录只说明“Runtime 支持什么”，不是用户授权结果。
当前名称映射足够，不引入复杂 Capability revision/binding 或通用 Runner；模板作为授权文件输入，不因换模板复制 Workflow。
模型策略继续由 Python 维护：可能包含图片的 Capability 从首轮起使用支持图片的默认模型，无需为此新增 Subagent。当前未实现按能力选择模型，见 2.8。

### 1.2 业务字段与关联

建议继续使用现有发送路径 `POST /api/v1/chat/conversations/{conversationId}/messages`；请求可整理为：

```json
{"content":"请整理附件成报告","attachmentIds":["file_01"],"capabilityRef":"document-writing","payload":{"reportTitle":"年度报告","year":2026}}
```

| 建议字段 | 作用与传递 |
| --- | --- |
| 路径 conversationId | Java 校验归属后转为 businessSessionId，已有业务会话不需再造会话 ID。 |
| content | 转为 Python input.text，也对应 Dify query；query() 本身是 SDK 调用，不是业务 ID。 |
| attachmentIds[] | Java 校验文件归属后转为 input.attachmentRefs[]，缺省 purpose 使用 input。 |
| capabilityRef | 可省略并由 Java 取 Agent 默认值；Java 发给 Python 时必须确定具体值。 |
| payload | 推荐新增的业务 JSON；Java 按能力校验后传递。现有 Java 的 Dify inputs 不等同于此字段。 |
| Java messageId | 沿用当前 Bridge 的助手消息 ID，关联输出；用户消息通过现有回复关系关联。 |
| Java runId | 一次执行；网络重提交复用，新执行/重新生成使用新值；无需 turnId。 |

建议 Java 保存 `runId/messageId/conversationId/capabilityRef/backend/status/lastConsumedSequence` 和必要的内部后端引用。持久化已处理序号后再转发，支持断线回放；Python 的 lastSequence 是服务端最大序号，不能当作 Java 已消费序号。SDK Session 仍由 Python 私有维护。
同会话同能力的后续执行推荐自动恢复上下文并串行运行；失败后的重新执行需考虑工具已发生的副作用，resume 不是任务恢复或事务回滚。

### 1.3 前端事件与展示

推荐在 Java 现有 SSE 形状上扩展；以下是建议，当前 Bridge 尚未提供 status/file 事件：

```json
{"event":"status","run_id":"run_01","local_message_id":"message_01","sequence":4,"phase":"downloading_file","fileId":"file_01","receivedBytes":512,"totalBytes":1024}
```

| 建议事件/字段 | 展示与转换 |
| --- | --- |
| stream_meta：run_id/task_id/local_message_id | 关联助手消息和停止操作；Python 路径的 task_id 可继续取 runId，Dify task_id 由 Java 内部记录。 |
| message：answer、content_type=answer | 仅追加正文。Python textDelta 是增量，按序号去重，不使用前后缀猜测去重，以免丢失合法重复文字。 |
| status：phase | queued 排队；文件准备显示“正在准备附件/模板”；校验显示“正在校验文件”；model_starting 处理；只有 thinking 显示思考。 |
| status：fileId/receivedBytes/totalBytes | 映射已知附件显示字节进度；未知总量用不定进度，下载 100% 不表示回答完成。 |
| status：toolCallId/status/isError | 工具运行/完成/失败；使用通用标签，省略原始 toolName。工具失败不自动等同于 Run 失败。 |
| file：fileId/fileName/fileSize/url | Java 归档后提供受 ACL 保护的预览/下载，对接现有附件组件。不要把 Runtime 下载 URL 直接交给浏览器。 |
| message_end：status；error：code/message | 区分 completed、stopped、failed；取消保留已有正文，连接结束不能直接算成功。 |
| sequence/run_id | 同 Run 内排序去重；Java 合并多来源或增加文件事件时应生成统一的 Java 序号，另存 Python 游标。 |

Java 仅转发正文、业务阶段、泛化工具状态和授权文件；原始工具参数/结果、SQL、地址、凭据、SDK Session 与思考正文不进入业务页面。

## 2. 当前实现与接入约定（按源码核对）

### 2.1 Java 和前端已有什么

Java 的 `service/chat/impl/ChatServiceImpl.java` 先保存用户/助手消息；仅当 runtimeEnabled=true 且传了 capabilityRef 时走 ClaudeRuntimeChatBridge，否则走 Dify。开关默认 false。
Bridge 经 `RuntimeRequestFactory -> ClaudeRuntimeAdapter -> RuntimeJwtSigner/PythonRuntimeClient` 创建 Run、读取 SSE、保存回答；运行映射目前只在内存。停止经现有 `/conversations/{id}/stop` 或消息级 `/stop?taskId=...` 调用 Runtime `/cancel`。
前端 `src/api/chat/index.js -> src/shared/ai/composables/useAiApp.js` 已可发送 content、attachmentIds、可选 capabilityRef，消费 message/agent_thought/message_end；未实现推荐的独立工具/文件进度事件。

| 当前 Java/前端报文 | 示例与字段 |
| --- | --- |
| 前端发送 POST /api/v1/chat/conversations/session_01/messages | `{"content":"整理附件","attachmentIds":["file_01"],"capabilityRef":"writing-docx"}`；content 上限 4000 字符，attachmentIds 是业务附件引用；这里保留 Java 当前旧能力名用于说明差异。 |
| Bridge 启动后的 SSE data | `{"event":"stream_meta","task_id":"run_01","run_id":"run_01"}`；task_id/run_id 均取此次生成的 Run ID。 |
| Bridge 正文 SSE data | `{"event":"message","message_id":"message_01","local_message_id":"message_01","content_type":"answer","answer":"回复片段"}`；两个消息字段均是 Java 助手消息 ID，answer 来自 Python textDelta。 |
| Bridge 阶段/终态 | 阶段变为 event=agent_thought、content_type=thinking，无阶段详情；成功变 message_end；取消和失败均变 error，附 message；没有 sequence。 |

以上是源码中的构造行为，当前旧请求尚无法通过 Python 校验，不能当作联调成功报文。
以下 2.2 至 2.7 是 Python 已实现、Java 对接必须匹配的字段，不代表当前 Java DTO 已匹配；现状差异见 2.8。

### 2.2 鉴权：Java -> Python

Runtime 请求统一使用 `Authorization: Bearer <JWT>`。Run 接口使用绑定本次执行的 Run JWT；能力目录接口使用带 `capability.read` 权限的 JWT（下文称 Catalog JWT），用于 Java 查询 Python 支持哪些能力。两者采用相同的签名与校验配置，区别在权限和绑定字段，目录查询无需先创建 Run。签名算法 HS256，Java/Python 共享密钥；Python 配置为 `CCSDK_RUNTIME_JWT_SECRET`、`CCSDK_RUNTIME_JWT_ISSUER`、`CCSDK_RUNTIME_JWT_AUDIENCE`。业务 Token 不能替代 JWT。Java 转发时不携带浏览器 Origin 头，Runtime 收到非空 Origin 会返回 403；浏览器只访问 Java。
JWT 解码示例（时间为演示值，实际按签发时刻生成；不是可直接使用的 Token）：

```json
{"iss":"string-ai-center-service","aud":"ccsdk-runtime","iat":1789012000,"exp":1789012600,"jti":"jti_01","sub":"user_01","tenant":"tenant_01","runId":"run_01","capabilityRef":"document-writing","businessSessionId":"session_01","messageId":"message_01","scope":"run.execute"}
```

| JWT 字段 | 必需性与校验 |
| --- | --- |
| iss/aud | 匹配部署配置，默认上例值；aud 可为字符串或包含目标值的数组。 |
| iat/exp | 数值，Unix 秒；exp 大于 iat，默认允许 5 秒时钟偏差。 |
| jti | 非空唯一字符串；创建与控制消费防重放，查询/订阅/目录不消费；重试创建须新签 jti。 |
| sub/tenant | Run 接口必须有用户/租户；Python 仅从已验证 JWT 取身份，不接受正文 context。 |
| runId/capabilityRef | Run 接口必须有，与请求或已保存 Run 一致。 |
| businessSessionId | 请求/记录存在时必须匹配；无会话请求建议正文和 JWT 一起省略。 |
| messageId | 创建时必须匹配正文；后续查询/控制不再检查。 |
| scope | 一个字符串或字符串数组，按接口校验；不能把多个 scope 拼成空格字符串。 |
| 能力目录 JWT | 保留 iss/aud/iat/exp/jti；sub 由 Java 填服务身份（Python 仅校验非空），scope=capability.read，不要求 tenant、runId、capabilityRef、businessSessionId 或 messageId。 |

鉴权成功继续执行，没有独立登录返回接口；缺失/失效/绑定不符返回 HTTP 401 纯文本，JWT 密钥未配置时目录、创建等接口返回 503。已存在 Run 另校验保存的 tenant/sub。来源：[auth.py](../../python/runtime/auth.py)、server.py 的 `_authorize_new_request/_authorize_internal`。
`credentials.platformBearer` 是另一路业务凭据：只按 MCP_AUTH_RULES 注入本次获准的 business MCP；db/docx/artifacts 不接收，不写 Prompt、事件和持久记录。仅持有 Token 不会增加 MCP 权限。

### 2.3 能力目录：Java -> Python

`GET /internal/v1/capabilities`，无请求正文。Java 签发目录读取 JWT，通过 `Authorization: Bearer <JWT>` 发送；解码后的字段示例如下（时间仅演示，实际须签名）：

```json
{"iss":"string-ai-center-service","aud":"ccsdk-runtime","iat":1789012000,"exp":1789012600,"jti":"catalog_01","sub":"string-ai-center-service","scope":"capability.read"}
```

仅含上述权限的 JWT 不能创建或控制 Run；缺少 JWT 或缺少 capability.read 返回 401。HTTP 200 返回完整登记目录，由 Java 再做用户权限筛选，不能直接视为当前用户可用列表：

```json
{"capabilities":[{"capabilityRef":"conversation","name":"通用对话","description":"日常交流、内容总结与问题解答","supportsAttachments":true},{"capabilityRef":"document-writing","name":"文档撰写","description":"起草、修改与生成 Word 文档","supportsAttachments":true},{"capabilityRef":"national-excellence-data-qa","name":"双高问数","description":"查询国双高项目、任务、资金与绩效","supportsAttachments":false}]}
```

| 字段 | 作用 |
| --- | --- |
| capabilities[].capabilityRef | 业务标识；内部依次映射无 Workflow、writing-docx、database-qa。 |
| name/description | 展示名称与说明，Java 可加业务展示配置。 |
| supportsAttachments | 布尔，是否允许 attachmentRefs；不是图片识别能力声明。 |

来源：[capabilities.py](../../python/runtime/capabilities.py)。内部 Workflow、Skill、MCP 和模型配置不在目录中返回。

### 2.4 创建 Run：Java -> Python -> SDK

`POST /internal/v1/runs`，Content-Type: application/json，JWT scope=run.execute。最小正文及带文件/业务参数/凭据的正文分别为：

```json
{"protocol":"agent-run/v1","runId":"run_01","messageId":"message_01","capabilityRef":"conversation","input":{"text":"你好"}}
```

```json
{"protocol":"agent-run/v1","runId":"run_01","messageId":"message_01","businessSessionId":"session_01","capabilityRef":"document-writing","input":{"text":"请整理附件成报告","attachmentRefs":[{"fileId":"file_01","purpose":"input"}]},"payload":{"reportTitle":"年度报告","year":2026},"credentials":{"platformBearer":"<仅业务 MCP 需要时传入>"}}
```

两个示例是互斥的创建场景，不能按顺序以同一 runId 提交不同内容。

| 请求字段 | 类型/必填 | Python 处理与 SDK 去向 |
| --- | --- | --- |
| protocol | string/是 | 仅 agent-run/v1，不传 SDK。 |
| runId | string/是 | 幂等、执行、事件和取消键；SDK 没有对应业务 Run ID。 |
| messageId | string/是 | 私有消息关联，不作为 SDK session，也不在 Run 响应回传。 |
| businessSessionId | string/否 | Client 的 tenant:sub:businessSessionId:capabilityRef 会话键；缺失取 runId，不保证跨 Run 连续。 |
| capabilityRef | string/是 | 映射 Workflow，配置装配为 ClaudeAgentOptions；字符串本身不是 SDK 参数。 |
| input | object/是 | 只接收 text、attachmentRefs。 |
| input.text | string/否，默认空 | 最多 100 万字符；与业务数据、附件清单合成 prompt，传给 query() 或 client.query()。 |
| input.attachmentRefs | array/否，默认空 | 最多 64 项；全部预取、校验完成后再调用模型。 |
| attachmentRefs[].fileId | string/是 | Java 文件 ID，交 File Broker；SDK 接收已授权本地文件清单及目录访问配置。 |
| attachmentRefs[].purpose | string/否 | input 或 reference，默认 input；是用途说明，不是额外权限。 |
| payload | object/否 | JSON 业务数据，最多 64 KiB、16 层；序列化进入 prompt，不参与模型/工具/权限配置。 |
| credentials.platformBearer | string/条件 | 最多 16384 字符；业务 MCP 需要时必需，经 Worker 临时传值到指定 MCP header/env，不送模型。 |

ID 字段须匹配 `[A-Za-z0-9][A-Za-z0-9_-]{0,255}`，HTTP 创建正文另有 2 MiB 总限制。text、附件、payload 至少一个非空；未知顶层字段返回 400，包括旧的 turnId、execution、runtime、context。payload 保留字段与递归过滤见 [Runtime 规范](ccsdk-runtime-interface.md#34-业务-payload)；过滤不能替代 Java 对模型可见数据的业务校验。
内部链为 `AgentRunRequest -> Capability/Workflow -> 文件准备 -> Worker JSONL -> config.build_options -> claude_sdk Facade -> SDK`。默认模型取 SCRIBE_MODELS 首项，未配置则取 ANTHROPIC_MODEL；Workflow 的 skills 进入 SDK skills，MCP 来自 Python 受控配置，cwd/add_dirs 来自 Runtime。

新建 HTTP 202；相同身份与非秘密请求重提交返回 HTTP 200，凭据刷新不影响幂等摘要；请求不同返回 HTTP 409 纯文本 `Run request mismatch: run_01`。创建响应：

```json
{"run":{"runId":"run_01","status":"queued","lastSequence":0},"eventsUrl":"/internal/v1/runs/run_01/events"}
```

来源：[protocol.py](../../python/runtime/protocol.py)、[config.py](../../python/runtime/config.py)、[run_store.py](../../python/runtime/run_store.py)、server.py。进程重启后的重提交可能重执行，不能宣称 exactly-once，见 2.8。

### 2.5 查询、控制与 SSE：Java -> Python -> Java

| 请求 | 输入与鉴权 | 输出 |
| --- | --- | --- |
| GET /internal/v1/runs/{runId} | 路径 runId；run.read 或 run.execute；无正文 | HTTP 200：`{"run":{"runId":"run_01","status":"running","lastSequence":3}}` |
| POST /internal/v1/runs/{runId}/control | run.control 或 run.cancel；正文仅 `{"option":"cancel"}` 或 `{"option":"interrupt"}` | HTTP 200 同一 run 结构，例如 status=cancelled；控制可能仍在收尾。 |
| POST /internal/v1/runs/{runId}/cancel | run.control 或 run.cancel；无正文 | 等同 option=cancel。 |
| GET /internal/v1/runs/{runId}/events?afterSequence=3 | run.read 或 run.execute；Accept: text/event-stream；非负整数游标，未传取 Last-Event-ID，再默认 0 | HTTP 200 SSE，返回大于游标的事件；参数优先。 |

`run.status` 为 queued/running/succeeded/failed/cancelled；lastSequence 为服务端已保存的最大整数序号，失败可有 error: string。响应不包含 messageId、身份、Provider Session、内部目录。
停止按钮用 cancel。interrupt 请求中断当前 SDK 响应，不是暂停：准备文件期间及独立 Query 会取消，Client 模型阶段的终态由 SDK 结果决定；两者都不撤销已执行的工具操作。终态 Run 再控制不会改变状态。
应用错误是纯文本：正文/未知能力/不允许附件 400，鉴权 401，Origin 拒绝 403，缺 Run/文件 404，幂等或控制冲突 409，配置不可用 503，控制超时 504；FastAPI 的非法 afterSequence 参数返回 422 JSON detail。创建后执行失败通过 run.failed 通知，不改写先前 202。

SSE 完整示例（帧末有空行）：

```text
id: 4
event: phase
data: {"protocolVersion":"agent-events/v1","eventId":"evt_04","runId":"run_01","sequence":4,"occurredAt":1789012000000,"type":"phase","payload":{"name":"downloading_file","fileId":"file_01","receivedBytes":512,"totalBytes":1024}}

```

| 字段/事件 | 实际字段与含义 |
| --- | --- |
| 公共信封 | protocolVersion 固定 agent-events/v1；eventId 为事件标识；runId 关联执行；sequence 从 1 递增；occurredAt 为 Unix 毫秒；type 决定 payload。 |
| run.started | payload.status=running；此时可能仍在准备文件或等待 Client，不表示模型已启动。 |
| phase | name：queued、preparing_files、preparing_file、downloading_file、validating_file、file_ready、files_ready、model_starting、started、thinking、response、working。 |
| 文件 phase | 按阶段可带 fileId、fileCount、receivedBytes、totalBytes；数值分别为数量/字节，不是百分比。 |
| message.delta | payload.textDelta: string，正文增量。 |
| tool.started/progress/finished | status=started/running/finished，scope 默认 main；可带 toolCallId、toolName；finished 有 isError 布尔。当前 Python 返回工具名，Java 面向浏览器应筛除。 |
| run.completed | 可带 inputTokens/outputTokens/turns 整数统计，也可为空对象。 |
| run.failed | code，如 timeout、sdk_execution_error、file_access_denied、file_validation_failed；可能带统计。 |
| run.cancelled | 空 payload，当前执行已取消。 |

SSE 断开只移除订阅，不取消执行；终态后关闭，空闲发送注释心跳。没有 artifact.created 事件，产物使用下一节接口拉取。完整回放的限制见 2.8。来源：server.py、run_store.py。

### 2.6 输入文件：Python -> Java File Broker

Java 先完成上传/模板选择与 ACL 登记，再将 fileId 随 Run 提交。Python 只预取 attachmentRefs，不从正文/payload 猜文件 ID，不列举 Java 文件库。后续再用原文件，Java 重新提交引用。
Python 向部署配置 CCSDK_FILE_BROKER_URL 发出 HTTPS POST，Content-Type: application/json，Accept: application/json, application/octet-stream：

```json
{"runId":"run_01","fileId":"file_01","purpose":"input"}
```

三个字段均为字符串，分别确定本次执行、文件和用途。默认 Authorization 使用原 Run JWT；CCSDK_FILE_BROKER_AUTH_MODE=service 时只用 CCSDK_FILE_BROKER_SERVICE_TOKEN。正文不传身份；Java 从 JWT 或服务鉴权后的 Run 记录校验租户/用户、会话、文件及本次授权引用。
Java 返回以下两种结果之一。URL 模式 HTTP 200 application/json 示例（内容为 5 字节 hello；有效期须以实际返回时刻计算）：

```json
{"fileId":"file_01","name":"source.txt","mimeType":"text/plain","size":5,"sha256":"2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824","downloadUrl":"https://files.example.com/download/file_01","expiresAt":1789012300000,"oneTime":true}
```

代理流模式 HTTP 200 示例（正文为原始字节，不是 JSON）：

```http
Content-Type: application/octet-stream
X-File-Id: file_01
X-File-Name: source.txt
X-File-Mime-Type: text/plain
X-File-Size: 5
X-File-Sha256: 2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824

hello
```

| JSON 字段 / 代理流响应头 | 类型与要求 |
| --- | --- |
| fileId / X-File-Id | 必填 string，与请求一致。 |
| name / X-File-Name | 必填安全文件名，无目录；流模式也支持 Content-Disposition 文件名。 |
| mimeType / X-File-Mime-Type | 必填 string；下载 Content-Type 须匹配或为 application/octet-stream。 |
| size / X-File-Size | 必填非负字节数；流头为十进制字符串，不能用 Content-Length 替代。 |
| sha256 / X-File-Sha256 | 必填 64 位十六进制，核对实际字节；Java 须保证下载版本不变。 |
| downloadUrl | URL 模式必填，HTTPS/443、允许域名、公共 IP、无重定向；Python 不向此 URL 转发 Run JWT。私网文件服务器建议用 Broker 代理流。 |
| expiresAt / oneTime | URL 模式必填；推荐 Unix 毫秒（兼容秒），未来且最多 5 分钟；oneTime 必须 true，Java/存储服务负责兑现一次性消费。 |

Java 返回 401/403/404/409/410/424 时 Python 转为 file_access_denied；其他失败、下载过期、完整性错误各有稳定 code。Python 分块落临时文件、校验后原子移动，全部就绪才查询模型；取消/失败清理下载，Run 结束清理临时输入。传输成功不保证文档/图片工具可解析内容。
默认预算：单文件 256 MiB，文件准备 10 分钟，网络操作等待 15 秒，模型执行 5 分钟，Client 排队 5 分钟，分别计时。配置名与 TLS 选项见 [Runtime 规范](ccsdk-runtime-interface.md#84-大文件与超时)。Java 应流式代理并匹配超时；原 Run JWT 须覆盖后续文件授权，Python 不自动刷新；创建 jti 防重放不能阻止合法文件回调。
来源：[file_broker.py](../../python/runtime/file_broker.py)、server.py。这是 Python 已实现的回调契约；本次未在 Java 应用控制器找到对应 Broker 实现。

### 2.7 生成文件：Java -> Python -> Java 文件服务

| 请求 | 输入与鉴权 | 输出与字段 |
| --- | --- | --- |
| GET /internal/v1/runs/{runId}/artifacts | run.read 或 run.execute；无正文 | HTTP 200：`{"files":[{"name":"result.docx","size":2048}]}`；name 文件名、size 字节数，无 artifactId/业务 fileId。 |
| 同一路径 ?name=result.docx | 相同 JWT；name 取列表并 URL 编码 | HTTP 200 原始字节，Content-Disposition 下载文件名、Cache-Control: no-store；不是 JSON。 |

Python 列出 .deliverables 中普通文件，下载限制到该目录。Java 下载后登记到自身文件服务，生成业务 fileId、文件名、大小、受权 URL，再供前端展示或用于新 Run。Java 适配器尚无 Artifact 调用；Client 目录是会话级共享，不能直接把列表当作本 Run 新增文件，见 2.8。来源：server.py 的 internal_artifacts。

### 2.8 差异与问题记录

以下为 2026-09-10 源码核对结果；建议处理尚未实施，也不静默改变当前契约。

| 优先级 / 问题 | 当前证据与影响 | 建议处理 |
| --- | --- | --- |
| 阻断：Java 报文/能力不匹配 | Java 的 RuntimeRunRequest/Factory 仍发送 turnId、agentRef、execution、runtime、limits、context，Python 拒绝；Java 用 writing-docx/database-qa，Python 用 document-writing/national-excellence-data-qa；Java 也没传 payload。 | Java DTO/Factory 按 2.4 收敛，并读取 2.3 的业务名称。 |
| 阻断：凭据来源与业务 ACL | 前端的 getHeaders 发 token 头；Java 的 BusinessTokenResolver 只读 Authorization Bearer。UserContextHelper 反射取 tenant 或 org；Registry 只验证全局名称，未见用户/Agent 能力 ACL 与文件 ACL 闭环。 | 明确已认证上下文如何提供原业务 Token 与真实 tenant；先校验业务权限再签 JWT，不能默认 org 就是租户。 |
| 缺口：文件接入/前后端版本 | 前端调用附件登记、模板等接口，当前 Java 的 ChatController 无附件登记，未找到 Broker；RuntimeClient 无 Artifact API。重命名/删除方法也与前端不一致。 | 先确定对应 Java 分支及文件服务，再接 2.6/2.7；不能以本地前端 API 清单证明 Java 已支持。 |
| 缺口：状态与结束判定 | Bridge 将全部 phase 和工具开始/完成映射 agent_thought，忽略 tool.progress 与 sequence；SSE 无终态就 EOF 时仍可能保存 completed。Python toolName 也不符合之前期望的浏览器泛化展示。 | 单独映射准备/工具状态、序号及终态；异常断线查询/续订阅，Java 过滤原始工具名。 |
| 缺口：默认 resume 与图片模型 | server 的 Query payload 固定 resume=None；Client 仅 Actor 内持有会话，重建未从 RunStore 恢复。模型固定 MODELS[0]，无按 Capability 的图片模型配置。 | Python 实现持久会话查找与串行约束；图片能力首轮选视觉模型并验证图片读取；Java 不增加调度字段。 |
| 风险：同 Run 重执行 | server 在记录非终态但没有本进程 Task 时会重新启动同一 runId；Java Bridge 运行记录也只有内存。 | worker 丢失先核实状态/副作用，避免同 Run 自动再执行；实际重执行用新 runId，补 Java Run/Event 持久化。 |
| 风险：回放可能不完整 | RunStore.events_after 默认最多 500 条；SSE 未循环翻页，终态 Run 首批返回后关闭；大积压可能漏事件。 | 分页读到游标追平并覆盖 500 条以上回放；暂不宣称任意长度完整回放。 |
| 风险：产物不是 Run 快照 | Client 多个 Run 共用 .deliverables，旧 Run 列表可见其他轮文件，同名文件可能被后续覆盖。 | 保存每 Run 产物清单/不可变副本后归档，避免把会话目录绑定到一条消息。 |
| 部署限制 | SDK 非 direct 模式仍用 bypassPermissions 和完整工具预设；JWT replay cache 在进程内存。 | Capability 白名单不能代替进程/目录隔离；生产多实例前补共享防重放、租约及安全验收。 |

### 2.9 验证与工程要求

本次运行 `python -X utf8 -m unittest tests.test_runtime_protocol tests.test_runtime_http tests.test_runtime_boundary tests.test_file_broker tests.test_file_preparation tests.test_session_actor tests.test_claude_sdk`（目录 python）。共 56 项，首轮 55 项通过，1 项 Client 文件准备测试触发 sdk_timeout；该例仅给模型阶段 50 ms，单独复跑通过，保留时序稳定性待核实记录。测试使用本地模拟传输/SDK，不是 Java、真实模型或浏览器联调。
文档 JSON、相对文件链接、两个 Run 示例的解析、JWT 绑定及完整能力目录均已校验；另用内存 RunStore + TestClient 复现“终态 Run 保存 501 条、SSE 只返回 500 条”，未修改运行时代码。

| 要求 | 状态 | 依据与差距 |
| --- | --- | --- |
| REQ-001：业务 Token 按 MCP 注入 | 部分满足 | Python 按配置副本注入且不持久化凭据；Java/前端 Token 头不匹配、运行中凭据到期/撤销及真实透传仍待验收。 |
| REQ-002：前端只触发 Capability | 部分满足 | Python 已有独立业务标识与受控 Workflow 映射，拒绝执行配置；Java 新旧标识、用户/Agent/附件 ACL 与前端事件尚未闭环。 |

持续要求见 [工程要求清单](engineering-requirements.md)；其中旧日期的实现快照不能替代本次代码核对。
