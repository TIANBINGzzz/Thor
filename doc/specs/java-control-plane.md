# Java 业务层设计规范

## 1. 目标与边界

Java 是业务控制面，负责用户身份、业务会话、文件权限、Capability 目录、Run 生命周期和业务前端。Python Runtime 是执行面，负责受控 Capability 映射、SDK 调用、工具、状态和事件。Java 代码不在本仓库实现。

## 2. 模块职责

| 模块 | Java 必须负责 | Python Runtime 提供 |
|---|---|---|
| 鉴权 | 登录身份、业务授权、签发 Run JWT | 校验 JWT 签名、有效期、scope 与请求绑定 |
| 会话 | 生成和持久化 `businessSessionId`、消息关系、Capability 归属 | 维护 Provider Session/Client 执行上下文 |
| 文件 | 上传、ACL、`fileId`、删除和下载 | 按 File Broker 授权将输入文件放入 Run workspace |
| Capability | 接收业务侧选定的 `capabilityRef`，按业务权限校验后原样传给 Python | 将 `capabilityRef` 映射到内部 Workflow、Skill、MCP 和运行模式 |
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
  "input": {"text": "请整理这个文档", "attachmentRefs": []},
  "credentials": {"platformBearer": "..."}
}
```

`capabilityRef` 是唯一业务能力字段。不得提交 Workflow、Skill、模型、MCP、工作目录或工具参数。

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

## 7. Java 实现方式可自行决定

登录和业务库、页面、SSE 转发、消息队列、缓存、重试、限流和日志格式由 Java 自行选择，但不能改变上述字段、路径、鉴权绑定和事件语义。

## 8. 修改规范

修改前先判断所属模块；字段新增、删除或语义变化必须同时更新本文件、`doc/specs/ccsdk-runtime-interface.md` 和 `doc/python-api.html`，并补充协议测试。不得在接口文档写未实现或规划内容；本地自测通过 Next 中间层模拟 Java，不修改 Java 接口。
