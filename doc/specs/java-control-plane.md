# Java 业务层设计规范

## 1. 目标与边界

Java 是业务控制面，负责用户身份、业务会话、文件权限、Capability 目录、Run 生命周期和业务前端。Python Runtime 是执行面，负责受控 Capability 映射、SDK 调用、工具、状态和事件。Java 代码不在本仓库实现。

## 2. 模块职责

| 模块 | Java 必须负责 | Python Runtime 提供 |
|---|---|---|
| 鉴权 | 登录身份、业务授权、签发 Run JWT | 校验 JWT 签名、有效期、scope 与请求绑定 |
| 会话 | 生成和持久化 `businessSessionId`、消息关系、Capability 归属 | 维护 Provider Session/Client 执行上下文 |
| 文件 | 上传、ACL、`fileId`、删除和下载 | 按 File Broker 授权将输入文件放入 Run workspace |
| Capability | 获取 SDK 目录，配置业务展示与授权；选定标识原样传给 Python | `GET /internal/v1/capabilities`；内部映射 Workflow、Skill、MCP 和运行模式 |
| Run | 生成幂等 ID、转发事件、展示结果 | 执行 Agent、产生状态和公共事件 |

## 3. Run 请求

```http
POST /internal/v1/runs
Authorization: Bearer <Run JWT>
Content-Type: application/json
```

```json
{
  "protocol": "agent-run/v1",
  "runId": "run_01",
  "messageId": "message_01",
  "businessSessionId": "session_01",
  "capabilityRef": "document-writing",
  "payload": {"reportTitle": "年度工作报告", "year": 2026},
  "input": {"text": "请整理这个文档", "attachmentRefs": []},
  "credentials": {"platformBearer": "..."}
}
```

`capabilityRef` 是唯一业务能力字段。不得提交 Workflow、Skill、模型、MCP、工作目录或工具参数。

`payload` 是可选业务 JSON 对象：当前作为用户业务数据送入模型，支持嵌套对象和数组，最大 64 KiB、16 层。Java 应校验业务字段与数据权限，只传允许模型读取的数据，不放身份、凭据、文件二进制或运行配置；保留字段规则见 Runtime 规范。文件引用仍放 `input.attachmentRefs`。相同 Run 修改 payload 会触发幂等冲突。

目录调用：`GET /internal/v1/capabilities`，请求头 `Authorization: Bearer <Catalog JWT>`。复用服务端 HS256 密钥，必需 Claims 为 `iss/aud/iat/exp/jti/sub/scope`；sub 为 Java 服务身份，scope 为 `capability.read`，不需要 Run 标识或 tenant。返回 `capabilities` 数组，含 `capabilityRef/name/description/supportsAttachments`；Java 自行合并展示配置并按用户权限筛选。目录不是业务授权结果，不返回内部执行资产。

## 4. Run 返回与事件

创建、查询、控制和取消统一返回 `run`：仅包含 `runId`、`status`、`lastSequence`，失败时可带 `error`。身份和 SDK 执行信息由 Python 内部保存和校验，不回传给 Java。

创建返回 `202`，包含 `run.runId`、`run.status`、`run.lastSequence` 和 `eventsUrl`。状态查询：`GET /internal/v1/runs/{runId}`。事件：`GET /internal/v1/runs/{runId}/events?afterSequence=0`。控制：`POST /internal/v1/runs/{runId}/control`，请求为 `{ "option": "cancel" }` 或 `{ "option": "interrupt" }`。

公共事件包括 `run.started`、`phase`、`message.delta`、`tool.started`、`tool.progress`、`tool.finished`、`run.completed`、`run.failed`、`run.cancelled`。思考只返回状态，不返回思考正文。

## 5. 鉴权规范

控制字段使用必填字符串 `option`：业务前端“停止生成”发送 `cancel`，取消当前或排队 Run；`interrupt` 仅请求 SDK 中断当前响应，不是可恢复的暂停。持久 Client 的 interrupt 终态由 SDK 结果决定，独立执行停止后为 cancelled。两者都不删除业务会话、不回滚已有输出或工具操作；已结束的 Run 不改变状态。控制响应是当前状态，Java 应继续处理 SSE 终态或查询状态；继续对话创建新 Run。

所有 Run 接口均必须发送 `Authorization: Bearer <Run JWT>`，包括查询、SSE、Artifact 下载、控制和取消。正文的 `credentials.platformBearer` 只用于业务 MCP，不能代替请求头 JWT。幂等重试保留 `runId`，重新签发带新 `jti` 的 JWT。

Java 为每次 Runtime 请求签发 HS256 Run JWT，并放入 `Authorization: Bearer <token>`。签名密钥由 Java 与 Python Runtime 通过部署配置共享。JWT 必须包含：

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

创建 Run 使用 `run.execute`；查询、SSE 和 Artifact 使用 `run.read` 或 `run.execute`；控制使用 `run.control` 或 `run.cancel`。Python 校验签名、issuer、audience、有效期、jti 和 scope，创建及控制消费 jti 防重放。创建时校验请求与 JWT 的 `runId`、`capabilityRef`、业务会话、`messageId` 一致性；身份仅从已验证 JWT 的 `tenant`、`sub` 获取并保存，正文不提交 `context`。后续接口按已保存 Run 校验执行标识、能力、业务会话和身份，不再校验 `messageId`。业务 Token 只放在 `credentials.platformBearer`，不得写入日志、事件、Prompt 或持久化数据。

## 6. File Broker

### 6.1 交互与接口职责

预置模板和用户上传文件都先由 Java 文件服务保存。选择已有模板时显示“已选择”；只有用户本机到文件服务器的首次传输显示“上传中”。点击发送后，Java 创建 Run 并订阅 SSE，不等待 Python 下载完再响应前端。

| Java 必须实现的业务能力 | 对接方式 |
| --- | --- |
| 模板列表、文件上传和选择 | 返回业务 fileId；上传、列表路径由 Java 自定，不属于 Runtime 接口。 |
| 发送消息 | 校验能力、会话和文件权限，将本次 fileId 放入 attachmentRefs，调用 POST /internal/v1/runs。 |
| 文件授权/代理流 | 提供配置在 CCSDK_FILE_BROKER_URL 的 HTTPS POST 接口，按本节请求响应契约返回文件。 |
| 状态和进度转发 | 订阅 Run SSE，保留 sequence，按 phase 展示；重连从已处理序号续传。 |
| 停止生成 | 调用 control 的 option: cancel；准备期间也可取消，收到终态后结束界面等待。 |
| 生成文件下载 | 通过 Runtime Artifact 列表及下载接口取得文件，归档或转发给用户。 |

Java 将 `preparing_files/preparing_file/downloading_file` 展示为“正在准备模板”或“正在准备附件”，`validating_file` 为“正在校验文件”，`model_starting` 为“正在处理”；仅收到 thinking 才显示模型思考。下载进度按 fileId 的 receivedBytes / totalBytes 计算，不把文件下载 100% 当作 Run 完成。无附件的能力直接进入模型执行。

文件准备期间 `interrupt` 也会停止准备并进入 cancelled；业务前端统一使用 `cancel`。模型执行阶段的 interrupt 行为见控制说明。

### 6.2 文件来源

文件上传由 Java 接收并保存，返回 fileId。发送消息时，Java 将本次允许使用的 fileId 放入 Run 的 attachmentRefs；Python 执行前逐个向 Java 获取文件。Java 可以直接返回代理文件流，不需要另设对象存储。生成文件则由 Java 调用 Artifact 列表和下载接口取得，按业务需要归档到 Java 文件服务，再提供用户下载。

| 文件场景 | fileId 来源与传递 |
| --- | --- |
| 新上传附件 | Java 上传返回 fileId，发送消息时加入 attachmentRefs。 |
| 选择已有文件或模板 | Java 从业务文件记录取 fileId，校验 ACL 后加入 attachmentRefs；模板引用本身不构成新的 Runtime 模板接口。 |
| 后续一轮再次使用原文件 | Java 重新提交所需引用，Python 重新获取；不能假定 SDK 历史上下文等于文件仍可访问。 |
| 重试原 Run | 保持相同引用和业务输入；如果实际重新执行且需要下载，Java 重新授权获取文件。 |
| 复用生成的交付物 | Java 先下载并登记为业务文件，获得 fileId 后通过附件引用用于新 Run。 |

Python 当前只预取 attachmentRefs 中的文件；不会列举 Java 文件库，不从正文或 payload 猜测文件引用，也没有供模型任意按 fileId 回调下载的工具。只传文件名、URL 或 payload.fileId 都不会触发 File Broker。

Java 接收上传并保存文件 ACL。Python 向配置的 File Broker URL 发起：

```http
POST <file-broker-url>
Authorization: Bearer <Run JWT 或服务 Token>
Accept: application/json, application/octet-stream
Content-Type: application/json
```

```json
{"runId":"run_01","fileId":"file_01","purpose":"input"}
```

Java 必须先校验 `fileId` 属于当前用户和业务会话，再返回以下 JSON：

```json
{
  "fileId":"file_01",
  "name":"source.docx",
  "mimeType":"application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  "size":1024,
  "sha256":"<64位小写十六进制>",
  "downloadUrl":"https://files.example.com/one-time/file_01",
  "expiresAt":1725400300000,
  "oneTime":true
}
```

`downloadUrl` 必须是短时、一次性 HTTPS 地址且不重定向。也可返回代理流，但必须设置 `X-File-Id`、`X-File-Name`、`X-File-Mime-Type`、`X-File-Size`、`X-File-Sha256`，并在响应体中返回原始文件字节。Python 会校验文件名、MIME、大小、SHA-256、有效期和路径安全；Java 对无权或不存在文件返回 `401`、`403`、`404`、`409` 或 `410`。

### 6.3 大文件传输要求

建议 Java 代理文件流，按块读取文件服务器并写响应，不先将整个文件读入内存；预存文件大小和 SHA-256，确保下载期间文件版本不变。HTTP 流式响应可以省略 Content-Length，但完整性头 X-File-Size / X-File-Sha256 仍必须提供。响应不重定向，Python 断开后 Java 应结束对应流并释放资源。

Python 默认允许单文件 256 MiB；全部附件准备 10 分钟、模型执行 5 分钟、Client 排队 5 分钟分别计时，网络无数据等待上限默认 15 秒，配置名见 Runtime 规范。Java 和代理服务器应匹配大小、流式转发及超时，SSE 不缓冲；准备失败显示文件失败提示，不显示为模型思考失败。

使用 Run JWT 回调时，Java 应让有效期覆盖排队和后续各文件的授权请求；Python 不会自动刷新 Token。每个 fileId 都要校验属于该 Run 获准附件和当前身份的可访问范围。Run 创建的 jti 防重放不能让同一 Run 的后续合法文件授权全部失效；一次性约束针对每个下载 URL。也可使用已实现的 File Broker 服务 Token 模式，Java 按 runId 查找并校验业务归属。

无需新增独立文件准备任务接口。已有附件能力复用 Runtime 的统一准备流程；是否要求模板文件属于该能力的业务输入校验，由 Java 与相应 Python 能力共同约定。

## 7. Java 实现方式可自行决定

登录和业务库、页面、SSE 转发、消息队列、缓存、重试、限流和日志格式由 Java 自行选择，但不能改变上述字段、路径、鉴权绑定和事件语义。

## 8. 修改规范

修改前先判断所属模块；字段新增、删除或语义变化必须同时更新本文件、`doc/specs/ccsdk-runtime-interface.md` 和 `doc/python-api.html`，并补充协议测试。不得在接口文档写未实现或规划内容；本地自测通过 Next 中间层模拟 Java，不修改 Java 接口。
