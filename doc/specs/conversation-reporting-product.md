# 对话、能力选择与报告产品流程

2026-09-14，按用户确认：普通会话不传能力，用户可在同一业务会话中选择已开通能力。本文区分当前代码与产品目标；数据库和报告执行设计分别见[data](data-source-connections.md)、[report](template-batch-data-plan.md)。

## 角色与页面

| 页面/角色 | 职责 |
| --- | --- |
| 普通用户对话页 | 历史会话、消息、输入框、当前可选能力、附件、生成进度及成果下载 |
| 能力/模板选择 | 展示Java按用户授权返回的能力及模板；普通会话是未选择能力的默认状态 |
| 管理配置页 | 维护可用能力、模板绑定和默认材料；数据库凭据和执行文件路径不向普通用户开放 |
| Java控制面 | 登录、会话及文件归属、能力授权、消息记录、后端选择、Run映射与成果归档 |
| Python Runtime | 解析已授权请求、锁定执行配置、准备附件、执行SDK和工具、发布Run事件及成果 |

## 当前源码事实

| 实际入口 | 已有行为 | 与目标的差距 |
| --- | --- | --- |
| string-ai-center-web `src/shared/ai/composables/useAiApp.js` | `sendMessage(content, options)`仅在非空时发送capabilityRef；带当前conversationId及attachmentIds | 已支持可选能力报文；完整能力选择器、模板字段和下轮选择状态仍须接入 |
| 同项目 `src/views/ai/composables/useAiPage.js` / `src/modules/ai-embed/composables/useAiEmbedSession.js` | 主页面和嵌入页转交capabilityRef；共用发送、SSE、停止与会话状态 | 两种入口须使用相同选择与禁用规则 |
| string-ai-center-service `ChatServiceImpl.java` | runtimeEnabled且capabilityRef非空才路由Python，否则Dify | 普通会话省略能力时，后端选择须由可信Agent/部署配置决定，不能以字段是否存在决定后端 |
| 同项目 `RuntimeRequestFactory.java` | 仍构造execution、context、runtime等旧字段 | 与当前Python严格协议不匹配，需按接口规范更新；本次未修改外部Java仓库 |
| ScribePlayground `web/app/components/Chat.tsx` | 默认conversation，发送时总带能力；菜单选能力调用newChat并清空当前消息视图 | 目前是每会话固定能力的测试UI；不能作为同会话切换已验收的证据 |
| ScribePlayground `server/app.mjs` | 校验会话能力必须等于请求能力 | 改为每条消息验能力，并保留业务会话；本次未修改该独立项目 |
| CCSDKScribe协议与SDK | 本次接受省略capabilityRef；内部解析conversation；同业务会话各能力使用独立Client键 | 不会自动把另一能力的SDK历史、工具结果和权限复制到本轮 |

## 用户流程

1. 打开对话页，加载业务会话和Java返回的可用能力；默认无能力选择，直接输入即可发送普通消息。
2. 用户展开输入区的能力菜单，选择问数或文档撰写。选择仅改变下一次发送配置，保留当前会话、历史消息和草稿；不自动执行或新建会话。
3. 选择文档撰写后，可选已授权预制模板或普通写作。模板选择生成payload.templateKey；年份、统计截止日、学校/专业群和要求写在用户输入中，缺失业务条件由模型澄清。
4. 输入文件或参考文件先上传/注册到Java，消息仅携带业务附件引用；切换到不支持附件的能力时阻止发送并明确列出不兼容附件，不能静默删除文件或送给不适用能力。
5. 点击发送时锁定本轮能力、模板、输入和附件；Java完成授权，保存用户/助手消息并生成runId。Python校验JWT与消息绑定后启动执行。
6. 页面依次显示排队、附件准备、取数、撰写、校验、成果就绪。正文流式追加；原始SQL、工具参数/结果、连接信息和思考正文不进入业务页面。
7. 生成期间可以编辑下一轮草稿和选择下一轮能力，但新请求须遵守同会话串行限制；停止按钮只取消当前Run，不撤回已产生正文和已发布文件。
8. 报告完成时Java归档DOCX与核验摘要，显示可预览/下载文件。缺必填数据只能显示“草稿/待补充”，不能显示完整报告成功。
9. 下一轮可保留当前能力或清除选择回普通会话。清除能力同时清除能力专属模板参数，历史消息和已有成果仍留在同一业务会话。
10. 刷新或返回历史会话时，按Run重放消息与成果；重试使用原消息的能力/模板快照，不读取输入框的新选择。断开SSE仅停止订阅，不能当作停止执行。

## 传值与状态归属

| 场景/状态 | 约定 |
| --- | --- |
| 普通消息 | 省略capabilityRef；Python内部视为conversation，JWT中的能力绑定仍是conversation |
| 已选问数 | capabilityRef=national-excellence-data-qa；输入为业务问题，不接受数据库/SQL/策略配置字段 |
| 已选预制模板 | capabilityRef=document-writing；payload仅需templateKey=szpt-midterm或double-high-annual；input.text表达年度及业务要求 |
| 会话 | conversationId/businessSessionId只表示业务连续性；不等于数据库权限、能力或SDK session |
| 下一轮编辑状态 | selectedCapabilityRef、selectedTemplateKey、草稿和待发附件在前端维护，不修改已开始Run |
| 每条消息 | Java保存实际能力、模板、附件引用和Run；Python保存已解析包/查询/连接/策略版本 |
| 跨能力上下文 | Java可提供已授权对话摘要/引用材料；Python重新解析权限，禁止搬运旧数据库scope_ref/result_ref或连接凭据 |
| 配置变更 | 下一轮重新解析DataContext、策略和秘密文件；工具集合或模板变化重建Client，不在活动Run中原位换工具 |

普通Run示例：`{"protocol":"agent-run/v1","runId":"run_example","messageId":"msg_example","businessSessionId":"session_example","input":{"text":"请概括上述讨论"}}`。
本次未扩展HTTP历史消息字段：跨能力摘要应由Java以已授权业务输入/文件提供，具体来源与长度规则需控制面实现；不能声称切换能力就天然共享全部SDK记忆。

## 报告验收

数据集先执行依赖诊断，再按同源一致快照取数；固定格由程序填值，模型处理有证据的文字。报告数据必须逐项核验源库字段、原QuerySpec输出类型/单位、选定项目与期间、NULL/0、去重及派生计算。
成功要求：实值取数、独立核验、必填绑定覆盖、完整DOCX及版面检查。原模板额外要求40表/图片/分节保持；用户批准的年度适配版按其登记结构验收，不能冒充原模板全部自动化。真实Java下载仍需外部控制面接入。
本次已确认2025年至2025-12-31，专业群为当前两个双高项目，建设章节取一级任务。评分允许空白；无期内反馈明确表达，不能使用2026补录或主表当前值冒充历史实绩。取数失败、缺定义、无数据、无授权与取消分别呈现。

## 工程要求检查

| 要求 | 状态 | 依据 | 差距 |
| --- | --- | --- | --- |
| REQ-001 | 部分满足 | Python仍按MCP绑定业务Token，data/reports不接收；每Run重建数据上下文 | 真实Java Token透传、撤销及生产日志全链路待验收 |
| REQ-002 | 部分满足 | 可省略普通能力；已选能力按消息授权，模板/查询/连接保持内部化 | 外部Java旧协议及前端同会话选择器仍需对齐；本次只修改Python及产品规范 |
