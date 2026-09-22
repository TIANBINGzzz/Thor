# Java 控制面接入职责

本文只维护业务层职责与映射；字段和示例以 [API 参考](../python-api.html) 为准，执行语义见 [Runtime 契约](ccsdk-runtime-interface.md)。Java/前端不在本仓库，其生产接入须独立验收。

## 职责边界

| 层级 | 职责 |
| --- | --- |
| Java | 业务身份、租户、会话/消息、能力及文件 ACL；选择执行后端、签发 Run JWT、关联运行结果 |
| Python | 解析已授权能力、装配执行资产和本轮凭据、准备附件、执行 SDK、维护模型上下文和 Run |
| 前端 | 提交业务输入和获准引用；显示消息、阶段、工具状态和文件卡片 |

Python/Dify 等后端由 Java 的可信配置选择；不能因为省略 capabilityRef 就改变后端。Python 能力目录仅说明可执行能力，Java 须按当前用户和业务 Agent 权限筛选，不将目录等同于授权。

Workflow、Skill、模型、MCP 地址和工作目录由 Python 管理，不接收浏览器覆盖。业务 Token、Run JWT、模型密钥各有用途，不能互换；需要下游业务凭据时使用 credentials.platformBearer，按可信 MCP 规则选择性注入。

## 消息映射与会话

| Java 业务值 | Runtime 字段与约束 |
| --- | --- |
| conversationId | businessSessionId；先验证会话归属，同一会话保持稳定 |
| content | input.text；包含年份、范围、写作或生成要求 |
| attachmentIds | 授权并解析为文件服务 ID 后填 input.attachmentRefs；不能直接混用附件表 ID |
| capabilityRef | 本轮能力；省略时为 conversation，JWT 同样绑定 conversation |
| 模板选择 | payload.templateKey；只使用已登记值，见[模板契约](ccsdk-runtime-interface.md#34-业务-payload) |
| 助手消息 ID | messageId；Java 保存 runId 与消息的关联 |
| 一次执行 ID | runId；相同请求重试复用，重新执行/重新生成使用新值 |

- Java 保存会话/消息以及每次执行的能力、输入快照、状态和已消费序号；Python 的 lastSequence 是服务端最大值，不能代替 Java 已消费游标。
- Python 按 tenant、sub、businessSessionId 串行续接 SDK 历史，跨能力也连续；配置或凭据变化重建 Client 并恢复历史，Java 不生成 AI 摘要。
- 能力选择的界面恢复属于业务会话元数据，可采用最后一次请求值；Python 始终执行本轮授权值，不将省略能力解释成沿用上一轮能力。
- SDK resume 恢复上下文，不恢复旧进程或回滚工具副作用；重试须使用原请求快照，不能读取输入框的新选择。

## 附件与模板

1. Java 在创建 Run 前校验用户、租户、会话、文件及用途权限，把文件服务 fileId 放入附件引用。
2. Python 按可信 fileService 配置下载本轮文件；显式 File Broker 是另一种部署选择，不因平台下载失败自动回退。两种契约见[文件获取](ccsdk-runtime-interface.md#8-file-broker-模块)。
3. 自定义模板使用 document-writing、附件引用和文字要求，不传 templateKey；Python 读取结构后生成新稿，不自动登记预制模板。每次再次使用文件仍须提交引用。
4. 预制模板以 templateKey 选择；同时提交附件不覆盖预制模板。附件文字和模板内容均不授予新的数据或工具权限。

## 公共事件与成果

- Java 按 Run 和 sequence 去重、保存消费游标并转发；断线按游标续读，SSE EOF 不能当成成功，必要时查询 Run 状态。断开订阅不取消执行，停止使用 cancel。
- message.delta 仅追加正文；phase 和工具生命周期更新状态。工具显示使用 Python 的 displayName，空名称隐藏提示，工具失败不自动等同于 Run 失败。
- 原始思考、工具参数/结果、SQL、路径、凭据及 SDK 会话标识不进入业务页面。开发观测使用独立 run.observe 权限及部署开关，见[观测契约](ccsdk-runtime-interface.md#10-开发观测)。
- 一个回答可有多个文件和图片。按 artifactId 幂等更新卡片，按首次文件事件的 sequence 定位；正文与文件事件可交错，不按文件名覆盖，也不能只保存最后一个 ready。
- artifact.ready 才关联远端 fileId，再提供经过业务 ACL 的下载/预览。模型回答中的文件名、链接或“待上传”文字不能作为上传状态；状态以结构化文件事件为准。
- data.url 是内部存储路径，不推测公开下载地址。failed/unknown 与 Run 失败分别表达；本地快照可供授权恢复，但不证明远端已保存。

## 验收边界

接口示例和 Python 测试不能证明 Java 已完成业务授权、文件关联或前端展示。联调应覆盖同身份会话连续性与跨身份隔离、Token 更新/撤销、附件 ACL、断线回放、多文件/图片交错事件及异常终态。

[REQ-001/REQ-002](engineering-requirements.md)的生产授权、运行中撤销和隔离差距继续保留；本次文档整理不改变协议或外部实现。
