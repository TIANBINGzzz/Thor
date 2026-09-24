# CCSDK Runtime 执行契约

本文维护 Java/Python 的执行语义及文件边界；HTTP 路径、字段表、状态、错误码和可解析示例统一维护在 [API 参考](../python-api.html)，业务映射见 [Java 职责](java-control-plane.md)。接口变化同步参考页和协议测试，职责变化才更新 Java 文档；不复制实现教程或未实现接口。

## 1. 职责边界

Java 授权业务身份、Capability、会话和文件；Python 解析可信执行资产、准备输入、管理 SDK 历史并交付结果。Workflow、Skill、模型、MCP 地址、工具权限及工作目录不能由浏览器覆盖；持续约束见 [工程要求](engineering-requirements.md)。

## 2. 通用约定

Base URL 来自部署配置，JSON 使用 UTF-8，事件使用 SSE。runId 标识一次执行，messageId 关联业务消息，businessSessionId 关联业务会话；SDK session_id 只在 Python 内部管理，不返回业务接口或替代上述标识。

## 3. Run 请求模块

- 创建接口收到合法请求即返回 202，不等待文件或模型；同 runId 的同形请求返回 200，输入或归属冲突返回 409。传输重试保留原请求快照并使用新 JWT jti；重新执行使用新 runId。
- 省略或 null capabilityRef 归一为 conversation，JWT 仍须绑定该能力；空字符串拒绝。能力选择只作用于本轮，Python 不恢复前端选中值。
- 能力目录无需鉴权，只说明已登记能力，不代表用户授权、模型/MCP 健康或模板可用；Java 按业务权限筛选。
- 同 tenant、sub、businessSessionId 的 Run 串行续接 SDK 历史，跨能力也连续；配置/凭据变化重建 Client 并恢复历史。无业务会话不保证连续上下文，重启须保留 RunStore 和 SDK transcript。历史续接不回滚工具副作用。

### 3.4 业务 payload

- 业务要求放 input.text，文件放 input.attachmentRefs；当前仅 document-writing 选择预制模板时使用 payload.templateKey，登记值为 szpt-midterm。其他场景省略 payload 或传 {}，不自行新增字段。
- 所有现有能力支持附件普通问答，复用同一只读入口和本轮输入目录。支持UTF-8文字、DOCX、PDF及PNG/JPEG/WebP，读取上限20MiB；不支持的格式明确反馈。附件不改变业务工具权限，也不作为接口最新数据。
- 通用 JSON 校验仍可能接受未约定字段，尚无逐能力字段白名单；未拒绝不表示接口支持。大小、深度及保留字段见 [payload 字段参考](../python-api.html#business-payload)，Java 仅传允许模型读取的数据。
- templateKey 不是路径、数据库名或权限参数。省略/null 不选模板，其他非空值须通过登记、启用、能力及路径校验；校验在异步准备阶段，202 不代表模板通过。其他能力传非 null 模板值同样触发校验。
- 预制模板由 template.json 登记 DOCX、指南及来源绑定；本 Run 冻结实际资源版本。共同规则显式加载，指南仅按所选模板加载；缺失、越界或版本漂移失败，不静默省略。指标含义与 SQL 只维护在数据库包。
- 上传模板使用 document-writing、不传 templateKey，通过附件引用及文字说明用途；purpose 仅 input/reference。Python 参考结构和样式生成新稿，不自动登记模板、生成位置地图或扩大数据权限。再次使用须重新提交授权引用。
- 同时传 templateKey 和附件仍以预制模板为准，附件只补充材料。两类模板及无模板共用同一撰写流程，见 [共同规则](../../.claude/workflows/writing-docx/WORKFLOW.md)；工具成功或文件 ready 不代表业务及版式验收。
- 图表数据、单位和要求放 input.text，Mermaid 作为 message.delta 正文交付，不产生图表 Artifact；图像生成使用正文要求及参考附件，PNG 按 Artifact 交付。

## 4. Run 查询与控制模块

- Run 查询返回公开状态、最大事件序号及稳定错误码，不返回身份和 SDK 元数据；业务会话检索只返回公开执行摘要，不代替 Java 的会话/消息存储。
- 会话检索按 JWT 的 tenant、sub、businessSessionId 过滤，独立使用 session.read。按 createdAt/runId 倒序分页，cursor 原样传回，不能作为权限依据；分页不是数据库快照。无记录不证明 Java 会话不存在。
- cancel 取消排队或活动 Run；interrupt 不是暂停/恢复，文件准备期取消准备，持久 Client 模型期请求 SDK 中断、独立执行期停止任务。已结束 Run 不变，返回时可能仍在收尾，终态以事件或后续查询为准。
- 控制不删除业务会话、已有文件或已完成工具副作用；断开 SSE 不取消执行，继续对话创建新 Run。

## 5. SSE 事件模块

- 每 Run 的 sequence 从 1 递增。afterSequence 优先于 Last-Event-ID，只补发更大的序号；消费端保存已处理游标，不能用服务端 lastSequence 跳过尚未消费事件。回放不重新执行模型。
- message.delta 只追加新增正文；按 Run/sequence 去重。所有 payload 含 displayName，空值只隐藏状态提示，正文、文件及终态仍须处理。工具按 Run、scope、toolCallId 关联，失败不自动等于 Run 失败。
- 公共事件仅提供公开 toolKey 和显示名，不包含内部工具名、参数、结果、思考正文、Prompt、路径、凭据或 SDK 原始消息；显示字典只在 Python 维护。
- running 同时覆盖文件准备和模型执行。先顺序下载并核验全部附件，准备失败/取消时不启动模型，无附件跳过文件阶段；进度属于当前文件，不是整个 Run 的百分比，文件字节不经 SSE。
- SDK 结束后可进入 saving_files，等待已登记上传收尾；SSE EOF 不代表成功。run.completed 表示 SDK 成功，不保证全部文件 ready，文件状态须分别消费。

## 6. Artifact 模块

- 发布创建 artifactId 和不可变快照，父 Runtime 绑定可信 Run 并自动上传；同名再次发布是新版本。模型只得到 artifactId/name/size 交稿回执，不管理上传状态或下载链接。
- DOCX 快照须能作为 Word 文件打开，不接受文本冒充或 .docx.md；发布检查不替代事实、目录和版式核验。
- 文件状态及事件原子保存，仅 ready 带远端 fileId。Java 按 Run/messageId/artifactId 更新卡片、绑定 fileId 并校验下载 ACL；文件服务 data.url 不是公开下载地址。
- Python 内部仅重试 HTTP 500、2xx body state=500 及连接建立失败，最多 3 次、等待 2/5 秒，共用上传预算；不重跑模型、不提供外部重传 API。发送结果不确定为 unknown，不自动重传；重启只恢复 pending，原 uploading 转 unknown。
- 文件列表、详情和内容 GET 均限制本 Run、禁止缓存；本地快照可用于授权核验或人工恢复，不能证明远端 ready。取消不撤销已提交上传。

## 7. 鉴权模块

- Java 用部署共享密钥签发短期 HS256 Run JWT，Python 校验签名、issuer/audience、时间、jti、scope、身份及请求绑定。配置见 [鉴权字段](../python-api.html#auth)，密钥不进入浏览器、正文或日志。
- 身份仅来自已验 JWT 的 tenant/sub。创建绑定 runId、capabilityRef、messageId 和可选 businessSessionId；后续单 Run 操作对已保存归属校验，不再校验 messageId。
- 创建用 run.execute，读取用 run.read/run.execute，控制用 run.control/run.cancel；写操作消耗 jti，读取不消耗。session.read 和 run.observe 是独立授权，不能从普通 Run 权限推导。
- credentials.platformBearer 是不透明业务 Token，仅按服务端规则注入获准 MCP；不是 Runtime 身份来源，不写入 JWT、Prompt、事件或 Run 存储，不授予额外工具权限。

## 8. File Broker 模块

Java 先校验文件 ACL 并将业务附件 ID 解析为文件服务 fileId。Python 只下载本轮显式引用；后续再次使用仍须提交引用，不扫描文件库或从正文猜 ID。

默认通道使用可信 fileService 的 baseUrl/domainName/remoteUrl/downloadPath；字段见 [配置说明](../../config/README.md)。只发送部署路由头，不转发 Run JWT、业务 Token 或 Cookie，不跟随重定向。200 必须是原始文件流，文件名取 Content-Disposition；校验已声明长度并流式限额。平台未提供权威 SHA-256，本地摘要只记录实际输入，下载成功不证明业务授权。

显式设置 CCSDK_FILE_BROKER_URL 时改用 POST Broker，正文为 runId/fileId/purpose；默认以本次 Run JWT 鉴权，auth_mode=service 时使用专用服务 Token。Broker 必须重验文件与 Run 归属，不能只信正文身份；平台下载失败不会自动回退到 Broker。

| Broker 返回方式 | 必需契约 |
| --- | --- |
| 一次性 URL JSON | fileId 与请求一致；name、mimeType、size、sha256、downloadUrl、expiresAt、oneTime=true；URL 仅 HTTPS:443，TTL 不超过 5 分钟，主机在 CCSDK_FILE_BROKER_ALLOWED_HOSTS 内，所有 DNS 地址须为公网并固定已验证 IP；不转发鉴权头、不跟随重定向 |
| 原始文件流 | X-File-Id、X-File-Name、X-File-Mime-Type、X-File-Size、X-File-Sha256；Python 不直连业务附件表或存储，按声明核验文件 ID、大小和摘要 |

输入原子落盘后才交给 Agent；Client 在 `.scribe-runs/client-sessions/<scopeHash>/.current-input/`，Query 在 `.scribe-runs/work/<runId>/input/`，工作稿另存 `.work/`。失败、取消和终态清理临时输入，不删除平台原件、工作稿或发布快照。

排队、全部文件准备、单次网络等待、SDK 执行分别计时；默认与限制见 [超时字段](../python-api.html#file-broker)。平台下载还与 fileService.maxFileBytes/timeoutSeconds 取较小限额，单文件限制不是磁盘总配额。

## 9. 错误响应

- 校园 MCP 鉴权、连接、服务及返回结构失败仍发出工具错误，并将最终 Run 标为 failed，复用 sdk_execution_error；即使模型正常结束答复也不记成功。参数纠正、澄清和成功空结果不触发此映射，下一 Run 清空失败标记。

同步业务错误通常为 text/plain，查询参数校验 422 返回 JSON detail；状态映射见 [错误参考](../python-api.html#errors)。创建后发生的附件/模板/模型错误通过 run.failed 和 Run.error 表达，上传错误通过文件事件表达，不能只按 HTTP 202 或 SDK 成功判断交付。

## 10. 开发观测

启用 CCSDK_ENABLE_RUN_TRACE=1 且持有绑定原 Run 的 run.observe 才可读取 trace；默认关闭返回 404。分页序号独立于 SSE，响应 no-store，只采集启用后 SDK 实际返回的思考与工具事件，遮盖已知凭据、省略二进制及过长内容；不补录历史、不承诺完整内部推理。字段见 [观测参考](../python-api.html#run-trace)。
