# Runtime 共享持久状态设计

状态：**设计提案，未实施**；核对日期：2026-10-31。59 AI 库仅作只读结构与聚合检查，未执行 DDL 或修改数据；[候选 DDL](runtime-state-storage.sql) 不属于 Flyway 迁移。

## 1. 目标与现状依据

- 用户已确定：Python 负责排队；暂停只阻止下一条启动，当前任务仍用停止；Java 与 Python 读取同一份权威状态；进程丢失后从可证明安全的持久边界恢复。
- 实库 `ai_center_dev` 为 MySQL 8.0.45-36，16 张 InnoDB 表；已有会话、消息、附件、反馈和模板，没有 Runtime 队列、租约、控制命令或检查点表。
- Java 项目 `string-ai-center-service` 的实际入口为 `runtime/claudeagentsdk/ClaudeAgentSdkChatBridge.java`：wire `messageId` 是 **assistant 消息 ID**，`businessSessionId` 是 conversation ID；`ChatServiceImpl` 重新回答会复用 user 消息、另建 assistant，附件绑定 user 消息。
- Python [RunStore](../../python/runtime/run_store.py) 当前用 SQLite 保存 Run/事件/文件/引导回执/工作区；请求仅留摘要，引导不留正文；[SessionActor](../../python/runtime/session_actor.py) 的待执行邮箱在内存，不能靠现有记录独立恢复请求。
- `string-ai-center-web/prototype/index-v2.3.html` 还要求队列暂停/继续、编辑/移除、转引导及刷新恢复；停止按钮同时暂停后续队列，编辑队首时不允许被取走。

## 2. 方案与复用边界

采用用户提出的同库共享状态方向；具体建议为 **Java 业务表 + Python 负责更新的 Runtime 表**，不复制会话与消息，不增加第二份 queue_item。队列就是 Run 表中尚待执行的有序记录。
把运行租约塞进 message 会混淆 Dify 的消息状态及多次回答；继续由 Java/Python 各存一套状态则需双写对账，均不建议。新增表仍在现有 AI 库，Python 用受限账号访问 Runtime 表，不直接改业务消息表。

| 表 | 使用方式与权威职责 |
| --- | --- |
| 现有 `t_ai_center_conversation` | 继续保存归属、标题、agent、业务系统与软删除；`source` 仍表示 full_page/popup，不能用作执行 Provider |
| 现有 `t_ai_center_message` | 继续保存 user/assistant 正文、parent、展示状态；Runtime 的状态是调度权威，message.status 是 Java 的展示投影 |
| 现有 `t_ai_center_attachment` | 继续保存输入文件及 user 消息关联；反馈、自定义模板表照旧复用 |
| 新增 `t_ai_center_runtime_session` | 每个业务会话一行：暂停状态、顺序计数、活动 Run、SDK/工作区引用、租约及 Java 消费游标 |
| 新增 `t_ai_center_runtime_run` | 每次回答一行：输入快照、排队顺序、状态、检查点、重试关系；assistant 唯一，user 不唯一 |
| 新增 `t_ai_center_runtime_command` | 控制意图及幂等回执；复用它保存引导正文/回执，不再另建 steering/outbox 表 |
| 新增 `t_ai_center_runtime_event` | 可重放的脱敏公共事件；保留 Run sequence，另加 session sequence 支持会话级消费 |
| 新增 `t_ai_center_runtime_artifact` | 输出文件快照与 pending/uploading/ready/failed/unknown；与 Java 输入附件职责分开 |

## 3. 写入归属、事务与调度

1. **入队**：Java 验证当前身份、会话、Capability 和文件权限；同一事务建立 user 消息、assistant 占位（pending）、初始化 Runtime session、分配 queue_seq、插入 queued Run、追加会话级 queue.enqueued 事件并递增 revision。Run 自身就是持久任务，无需 enqueue outbox；request_key 在会话内去重，重复且内容不同返回冲突。
2. **控制**：Java 同事务插入 command、分配 command_seq 并追加 command.accepted 会话事件，前端先显示“请求处理中”；Python 提交状态转换、回执及事件后才显示已暂停/已保存。通知丢失不影响处理，Python 周期扫描数据库；按 command_seq **开始处理并持久化决定**，不等待前一条外部回执才处理下一条，避免 delivered 引导阻塞停止或编辑续约；领取下一 Run 前须处理已有 accepted 意图，cancel 等异步清理仍由 active_run_id 阻挡出队。
3. **单会话串行**：会话行短事务 `SELECT ... FOR UPDATE`，始终按 queue_seq 取最早 queued/waiting Run；队首缺授权或被编辑锁住时不绕过。队列暂停独立于当前 Run 状态，即使队列清空也保留，只有显式继续才恢复。
4. **竞争边界**：Java 插入命令、Python 出队都先锁 session；先提交的控制意图先处理。claim 先于 pause 提交则该条已是当前任务，暂停不撤销它；返回回执包含实际 activeRunId 与 revision，不能只靠按钮本地变色。
5. **租约**：session 持有 owner/lease_expires_at/lease_epoch，使用数据库 UTC 时间；每次接管递增 epoch。Worker 回写必须核对 owner、epoch、有效期及 active_run_id；会话内没有第二套 Run 租约。失去续租即停止派发新工具并尝试停止子进程，租约过期本身不证明外部工具已停止。
6. **原子边界**：运行状态、checkpoint、command 回执、artifact 状态和对应 event 在同一短事务更新；SDK/HTTP 调用不持有数据库锁。会话写入先锁 session，再依次操作涉及的业务消息/附件 → 按 ID 排序的 Run → command → artifact → event；死锁只重试数据库事务，不能因此重发外部调用。
7. **单写职责**：Java 创建 session/Run 初始值、命令及其初始事件，推进自己的投影游标；Python 决定其后的 Runtime 生命周期与回执。共同的事件序号和 revision 均在 session 行锁内递增；双方仅更新所属列并做条件更新，禁止 ORM 全行覆盖，初始状态也不得脱离事件事务。

## 4. 原型交互与控制语义

| 交互 | 持久行为与竞争规则 |
| --- | --- |
| 发送/重新回答 | 新 Run、新 assistant；重新回答复用 user 与附件，设置 retry_of_run_id，不覆盖旧结果 |
| 暂停/继续队列 | pause_queue/resume_queue 命令；仅更新 session.queue_state，不触发 SDK interrupt；关闭的会话不能继续 |
| 停止当前任务 | cancel_run 携带 pauseQueue=true，与暂停后续队列一并生效；完成取消清理才将 Run 置 cancelled 并释放活动位 |
| 移除待执行消息 | cancel_run 对 queued/waiting 原子置 cancelled；保留记录用于重试和审计，Java 隐藏占位；已开始则拒绝“仅移除”模式 |
| 编辑待执行消息 | acquire_edit/renew_edit/release_edit/save_edit；锁属浏览器编辑实例且有到期时间。保存须匹配 owner、未过期锁及 expected_run_revision，仅支持改文本，原子换输入快照并递增 revision；Java 随事件投影正文/关联；到期解除占位，旧保存请求返回冲突 |
| 直接引导 | steer_run：Java 新建 user 消息并同事务插入 command，messageId 使用这条补充消息 ID；不创建新 Run，默认不打断当前工具，沿用 accepted/delivered/applied/rejected/unknown 回执语义 |
| 排队转引导 | promote_to_steer 原子预留源 Run（redirecting）与目标 Run/command，复用源 user 消息；applied 后源 Run=redirected、Java 隐藏其 assistant。已确定未发送的拒绝才恢复原队位；发送后不确定则 steering_unknown，不能回队或自动重发 |
| 删除会话 | Java 软删除与 close_session 命令同事务；Python 关闭队列、取消未开始 Run、停止当前 Run；历史按统一保留策略清理 |
| 核对中断/未知 | resolve_uncertainty 命令按 Run/引导/成果指定对象与证据；恢复队列不隐式解决未知。事实无法核实则保留 unknown，用户可以明确放弃该次操作，不允许把放弃写成执行成功 |

编辑锁默认 60 秒、每 20 秒续约（本提案取值）；命令回执给 expiresAt/revision，页面拿到锁才进入编辑态；刷新不恢复未保存草稿，等待锁释放/到期。全队暂停不因编辑结束自动解除。
编辑输入若被其他回答共用，Java 保存请求时先创建 hidden 的替代 user 消息并复制获准附件关联，与 save_edit 命令同事务提交 replacement_user_message_id；Python 接受后原子换 Run.user_message_id/快照，Java 投影时重绑本次 assistant.parent 并显示新 user，旧问题/回答保持不变。拒绝则替代消息保持隐藏并按保留策略清理。普通独占输入可原位更新。Runtime 队列显示及重新回答均读取所选 Run.request_json/关联，不从滞后的 user.content 猜输入。
引导与转引导限定同身份、同会话、当前活动 Run、同 Capability 的**纯文本**，不接受附件、模板或权限变化；原型允许附件引导的行为需禁用并提示另行排队。未知回执必须保留，不能显示“已纳入”；delivered 只表示已交给 SDK，applied 也不证明每条要求都满足。

## 5. 身份、授权与输入快照

Runtime scope 固定为 tenant_id_ + user_id + conversation_id；复用 Java 已认定的主体值，不擅自把历史 userId 改成 userCode。旧表身份可空不代表新记录可空，缺身份拒绝，不以 default/visitor 补足。外键只保关系，Java 事务还必须验证消息角色、parent、归属及文件 ACL。
request_json 仅保存版本化、白名单化的 input/payload/能力与授权文件 ID；不保存 credentials、Authorization、JWT、业务 Token、供应商密钥、签名 URL 或运行环境。用户输入可含业务敏感信息，继承业务会话的访问与保留策略；不进入普通日志。
Python 校验并生成 request_hash；出队前向 Java 请求本次有效授权，绑定 Run、身份、Capability、输入 revision/hash 与 lease_epoch。Java 重新检查会话/能力/文件权限，按需从已认证请求或受控在线会话取得业务 Token，仅通过内存传输；需要却无法取得则 waiting/authorization_required，用户重新认证后才继续。不需业务 Token 的能力仍须 Java 重新核权后签发 Run JWT；不能把入队时的授权快照当永久权限。
仍按当前聊天主链路划分读/执行控制权限，不恢复独立 run.steer 权限；鉴权签发、回调授权与业务 Token 生命周期需 Java 接入。可信资产解析后的无秘密 execution_snapshot 保存配置引用/摘要及部署版本；所需版本或工作区不可用时等待/失败，不能静默换新版本继续。

## 6. 恢复边界与事件投影

| 故障位置 | 重启后的动作 |
| --- | --- |
| 浏览器刷新或 Java 重启 | Java 从共享 Run/session 查队列；独立后台消费 event，消息正文/文件卡片与 projected_event_seq 同事务更新，重复消费无重复追加；不依赖浏览器 SSE 存活 |
| Python 尚未领取或尚未发送 SDK | 原顺序和暂停状态保留；安全的文件准备可重新校验/下载，重新获取授权后继续；claim 不代表模型开始，SDK 发送前先持久化 sdk_started_at |
| SDK 已发送，尚无持久 result | 标 interrupted，保留部分输出、活动位并暂停队列；resolve_uncertainty 经 Java 核验旧进程停止及副作用处置证据后，Python 才清除活动位。resume_queue 此前返回 recovery_required；用户重新回答另建 Run，不能宣称从任意 SDK 工具继续 |
| SDK result 已持久化 | checkpoint=sdk_result_saved 与 result 事件原子保存；恢复进入 finalizing，仅补投影/成果交付，不再调用模型；已上传不再上传 |
| 引导发送过程中中断 | 发送前将 command=processing 持久化；无法证明未发送或已纳入则 unknown，绝不自动再次注入；源队列转引导保持非可执行状态 |
| 成果上传中断 | pending 可继续；uploading 转 unknown，须按 artifactId 向文件服务核对。只有上游支持幂等键或能确认未上传时才重试，否则人工处理 |

数据库保存检查点和引用；SDK transcript、输入缓存、成果快照另存持久数据卷/对象存储，workspace_id 使用不含宿主机路径的受控引用。仅有 session_id 不能恢复丢失的历史文件；跨节点接管必须能读取同一份文件并排除旧进程继续写入，首期仍保持单部署实例。
处理中断后不复用可能含未完成工具调用的 transcript；核对解除后，新建干净 SDK 会话，以已完成 Run 的持久输入/公开结果及已确认引导装配上下文，记录新 SDK 引用；这是语义续接，不能保证复原原推理。源队列转引导 unknown 可明确放弃并将源 Run 取消，原引导回执仍保留 unknown；不得同时回队重跑。成果 unknown 与 Run 终态独立，核实已有 fileId 才改 ready，无法核实则保留并记录放弃决定，不自动重传。
Run sequence 继续用于现有 agent-events/v1；session sequence 用于新增会话级队列/命令增量，不能混用为旧 SSE eventId。Java 历史快照带 **projected_event_seq**，前端从该游标补增量，而非从可能领先的 last_event_seq 开始；若快照展示了更新的 Run revision，前端按 revision 去重。事件清理必须越过 Java 投影游标并满足保留窗口；前端游标过期返回 replay_expired 并重新拉快照，不能静默漏事件。
普通 Agent 首期只定义 input_prepared/sdk_result_saved 安全检查点。未来真正编排需要节点级输入、结果、重试和副作用幂等记录，选定编排执行器后再增加 step 表/其原生检查点；本提案不虚构通用 DAG，也不把普通 SDK tool 调用当可安全重跑节点。

## 7. 实施范围与验收门槛

需要 Java 改造入队事务、控制命令、临执行授权、后台事件投影及 stale-streaming 修复（不得再凭内存/正文猜终态）；Python 将 RunStore/Actor 调度改为同库状态、租约与恢复；前端由 Java 快照/增量驱动交互。**不是只改 Python 就能完整实现。**
此 DDL 面向 Java 主链路的共享部署，要求预先存在业务会话/user/assistant；通用 agent-run/v1 当前允许省略 businessSessionId、ID 可达256字符，不能用本表把通用解析器静默收窄。实施时共享部署须显式校验业务映射，未登记请求返回 business_record_required；切换前盘点实际直连调用方并完成接入，独立无业务记录调用不在本次共享表范围，不另造影子业务消息或双写兼容层。
共享模式上线应在维护窗口排空/停止旧 Run，结束在途引导/上传并处置 unknown，登记必要 SDK 工作区，再切换唯一状态来源；不长期双写 SQLite/MySQL，也不从旧 request_hash 伪造完整请求。历史消息照旧可读，切换方案须在实际实施时验收。
本次只提交设计和候选 DDL；现有 [API HTML](../python-api.html) 继续准确描述已实现行为。实现后再同步新增接口、状态、鉴权与重试示例，不能现在标成已支持。
必须验收：并发入队不重单、两 worker 不同跑一会话、暂停/编辑/取消与出队竞争、转引导各发送窗口崩溃、SDK 前后断点、上传 unknown、旧 epoch 回写被拒、Java 断线重放无重复/漏字、跨身份/权限撤销与持久化出口无凭据。静态 DDL 检查不算这些验收通过。
本次核验：设计独立复核已完成；5 张新表及1条新表外键 ALTER 可被 MySQL 方言解析，15 组外键类型/排序规则/目标唯一键与实库结构快照一致，文档引用有效。本机 MySQL 镜像拉取两次失败，**未完成实机建表及事务恢复验证**；未对59执行候选 DDL。

| 要求 | 状态 | 依据 | 差距 |
| --- | --- | --- | --- |
| REQ-001 | 部分满足（方案覆盖，未实施验收） | 第5节：当前身份重新授权、三类凭据分离、仅内存按 MCP 注入 | Java 安全上下文来源、过期/撤销处理与全链路无泄漏须联调 |
| REQ-002 | 部分满足（方案覆盖，未实施验收） | 第2/5/6节：业务 Capability、服务端解析、运行关联、无秘密配置追溯、不虚构 Workflow | Java ACL、配置版本可恢复性、文件与进程隔离须独立验收 |
