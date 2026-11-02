# Runtime 共享持久状态设计

状态：**设计提案，未实施**；核对日期：2026-11-02。59 AI 库仅作只读结构与聚合检查，未执行 DDL 或修改数据；[候选 DDL](runtime-state-storage.sql) 不属于 Flyway 迁移。

## 1. 目标与现状依据

- 用户已确定：Python 负责排队；暂停只阻止下一条启动，当前任务仍用停止；Java 与 Python 读取同一份权威状态；进程丢失后从可证明安全的持久边界恢复。
- 实库 `ai_center_dev` 为 MySQL 8.0.45-36，16 张 InnoDB 表；已有会话、消息、附件、反馈和模板，没有 Runtime 队列、租约、控制命令或检查点表。
- Java 项目 `string-ai-center-service` 的实际入口为 `runtime/claudeagentsdk/ClaudeAgentSdkChatBridge.java`：wire `messageId` 是 **assistant 消息 ID**，`businessSessionId` 是 conversation ID；`ChatServiceImpl` 重新回答会复用 user 消息、另建 assistant，附件绑定 user 消息。
- Python [RunStore](../../python/runtime/run_store.py) 当前用 SQLite 保存 Run/事件/文件/引导回执/工作区；请求仅留摘要，引导不留正文；[SessionActor](../../python/runtime/session_actor.py) 的待执行邮箱在内存，不能靠现有记录独立恢复请求。
- `string-ai-center-web/prototype/index-v2.3.html` 还要求队列暂停/继续、编辑/移除、转引导及刷新恢复；停止按钮同时暂停后续队列，编辑队首时不允许被取走。
- 当前锁定 `claude-agent-sdk==0.2.171` 支持 `SessionStore` 外部镜像与 resume、按 transcript UUID fork；本 Runtime 目前只配置本地 resume，尚未接 SessionStore。

## 2. 方案与复用边界

采用用户提出的同库共享状态方向；具体建议为 **Java 业务表 + Python 负责更新的 Runtime 表**，不复制会话与消息，不增加第二份 queue_item。队列就是 Run 表中尚待执行的有序记录。
把运行租约塞进 message 会混淆 Dify 的消息状态及多次回答；继续由 Java/Python 各存一套状态则需双写对账，均不建议。新增表仍在现有 AI 库，Python 用受限账号访问 Runtime 表，不直接改业务消息表。

| 表 | 使用方式与权威职责 |
| --- | --- |
| 现有 `t_ai_center_conversation` | 继续保存归属、标题、agent、业务系统与软删除；`source` 仍表示 full_page/popup，不能用作执行 Provider |
| 现有 `t_ai_center_message` | 继续保存 user/assistant 正文、parent、展示状态；Runtime 的状态是调度权威，message.status 是 Java 的展示投影 |
| 现有 `t_ai_center_attachment` | 继续保存输入文件及 user 消息关联；反馈、自定义模板表照旧复用 |
| 新增 `t_ai_center_runtime_session` | 每个业务会话一行：暂停/活动 Run/队列计数、SDK 与工作区引用、租约 |
| 新增 `t_ai_center_runtime_run` | 每次回答一行：关联消息、输入 hash/version、顺序、状态、恢复点和重试关系 |
| 新增 `t_ai_center_runtime_event` | Run 公共事件回放，以及带 command_id 的控制意图和回执；不放 SDK 原始 transcript |
| 新增 `t_ai_center_runtime_transcript` | SDK SessionStore 原样条目，独立于前端事件流并按 SDK key/顺序读取 |
| 新增 `t_ai_center_runtime_artifact` | 输出文件状态与受控快照引用；文件字节留在持久文件存储，不塞进 MySQL 行 |

表可以按能力分层而不再增加队列项、命令或通用步骤表：**三张核心表**是 session、run、event；其中 Run 本身就是队列项，event 也保存控制命令账本。跨节点要使用 SDK `resume` 时，需要同库 transcript 表；要在重启后可靠续做成果上传并避免重复交付时，需要 artifact 表。它们仍全部落 MySQL，但首期不为尚未实现的编排 DAG 预建表。

必要字段是：session 的业务会话及身份范围、`queue_state/active_run_id/next_queue_seq/last_session_seq/revision/lease_owner/lease_epoch/lease_expires_at`；Run 的两条业务消息关联、`capability_ref/queue_seq/status/input_revision/input_hash/sdk_started_at/checkpoint_stage/transcript_sync_state`；event 的 `event_id/session_sequence/run_id/run_sequence/command_id/event_type/payload_hash/payload_json/occurred_at`。跨节点 SDK resume 还需 session 的 SDK/workspace 引用、Run 的可信执行配置摘要和 checkpoint UUID，以及 transcript 的 `(project_key, session_id, subpath)`、顺序和 JSON 条目；`entry_sha256` 用规范化 JSON 计算，因为 SDK 允许存取时改变对象键序。成果文件交付启用时另需 artifact 的状态与持久文件引用。编辑锁、重试/转引导关系、错误码和 Java 投影游标按启用的交互保留。

## 3. 写入归属、事务与调度

1. **入队**：Java 验证当前身份、会话、Capability 和文件权限；同一事务建立 user/assistant 消息、Runtime session/queued Run 和 queue.enqueued 事件并分配 queue_seq。Run 只引用 user 消息；其 content、已净化 inputs 和附件关系是执行输入的唯一业务快照，hash/version 用于校验，无需重复存 request_json。Run ID 复用为入队幂等键。
2. **控制**：Java 同事务追加带 command_id 的 command.accepted 事件（引导正文放现有 user 消息，事件只引用 messageId）；Python 按 session_seq 开始处理，另追加 processing/applied 等回执事件。事件表即命令账本，不另建 command 表；同 command_id 同 payload 幂等，不同 payload 直接冲突。Python 周期扫描保证通知丢失不漏处理。外部调用处理中断按 unknown，不重复发送；领取下一 Run 前须处理已接受意图。
3. **单会话串行**：会话行短事务 `SELECT ... FOR UPDATE`，始终按 queue_seq 取最早 queued/waiting Run；队首缺授权或被编辑锁住时不绕过。队列暂停独立于当前 Run 状态，即使队列清空也保留，只有显式继续才恢复。
4. **竞争边界**：Java 插入命令、Python 出队都先锁 session；先提交的控制意图先处理。claim 先于 pause 提交则该条已是当前任务，暂停不撤销它；返回回执包含实际 activeRunId 与 revision，不能只靠按钮本地变色。
5. **租约**：session 持有 owner/lease_expires_at/lease_epoch，使用数据库 UTC 时间；每次接管递增 epoch。Worker 回写必须核对 owner、epoch、有效期及 active_run_id；会话内没有第二套 Run 租约。失去续租即停止派发新工具并尝试停止子进程，租约过期本身不证明外部工具已停止。
6. **原子边界**：Runtime 当前状态与公共 event 同事务提交；SDK/HTTP 调用不持有 DB 锁。先锁 session，再依次操作业务消息/附件 → Run → artifact → event；死锁只重试 DB 事务，不能因此重发外部调用。MySQL 事务不能和 SDK 本地 transcript 写入组成一个原子事务，所以 transcript_sync_state 必须显式记录 pending/confirmed/unknown。
7. **单写职责**：Java 创建业务消息、queued Run 和 command.accepted event；Python 更新 Run、队列、回执、公共事件与 artifact 状态。双方仅更新所属列并做条件更新，禁止 ORM 全行覆盖；当前状态行是恢复依据，事件日志不声称完整 event sourcing。所有 session_sequence 和 run_sequence 都在锁定 session 的短事务内分配；run_sequence 可在该锁下按 Run 当前最大值递增。

## 4. 原型交互与控制语义

| 交互 | 持久行为与竞争规则 |
| --- | --- |
| 发送/重新回答 | 新 Run、新 assistant；重新回答复用 user 与附件，设置 retry_of_run_id，不覆盖旧结果 |
| 暂停/继续队列 | pause_queue/resume_queue 命令；仅更新 session.queue_state，不触发 SDK interrupt；关闭的会话不能继续 |
| 停止当前任务 | cancel_run 携带 pauseQueue=true，与暂停后续队列一并生效；完成取消清理才将 Run 置 cancelled 并释放活动位 |
| 移除待执行消息 | cancel_run 对 queued/waiting 原子置 cancelled；保留记录用于重试和审计，Java 隐藏占位；已开始则拒绝“仅移除”模式 |
| 编辑待执行消息 | acquire_edit/renew_edit/release_edit/save_edit；锁属浏览器编辑实例且有到期时间。保存须匹配 owner、未过期锁及 expected_run_revision，仅支持改文本，原子换输入快照并递增 revision；Java 随事件投影正文/关联；到期解除占位，旧保存请求返回冲突 |
| 直接引导 | steer_run：Java 新建 user 消息并追加 command.accepted event，ID 关联补充消息；不创建新 Run，默认不打断当前工具，沿用 accepted/delivered/applied/rejected/unknown 回执语义 |
| 排队转引导 | promote_to_steer 原子预留源 Run（redirecting）并追加目标 command event，复用源 user 消息；applied 后源 Run=redirected，Java 隐藏其 assistant。已确定未发送的拒绝才恢复原队位；发送后不确定则 steering_unknown，不能回队或自动重发 |
| 删除会话 | Java 软删除与 close_session 命令同事务；Python 关闭队列、取消未开始 Run、停止当前 Run；历史按统一保留策略清理 |
| 核对中断/未知 | resolve_uncertainty event 按 Run/引导/成果指定对象与证据；恢复队列不隐式解决未知。事实无法核实则保留 unknown，用户可以明确放弃该次操作，不允许把放弃写成执行成功 |

编辑锁默认 60 秒、每 20 秒续约（本提案取值）；命令回执给 expiresAt/revision，页面拿到锁才进入编辑态；刷新不恢复未保存草稿，等待锁释放/到期。全队暂停不因编辑结束自动解除。
编辑输入若被其他回答共用，Java 保存请求时先创建 hidden 的替代 user 消息并复制获准附件关联，与 save_edit event 同事务提交；应用时原子重绑本次 Run 和 assistant.parent，旧问题/回答保持不变。普通独占输入在锁和 expected_revision 下更新。所有执行方从关联 user 消息读取输入并校验 hash/version，不另存完整 request_json。
引导与转引导限定同身份、同会话、当前活动 Run、同 Capability 的**纯文本**，不接受附件、模板或权限变化；原型允许附件引导的行为需禁用并提示另行排队。未知回执必须保留，不能显示“已纳入”；delivered 只表示已交给 SDK，applied 也不证明每条要求都满足。

## 5. 身份、授权与输入快照

Runtime scope 固定为 tenant_id_ + user_id + conversation_id；主体只在 session 保留一份并沿用 Java 已认定标识。旧表身份可空不代表新 Runtime 可空；缺身份拒绝，不以 default/visitor 补足。Java 同事务核验消息角色、parent、归属及文件 ACL。Run 存 input_hash/revision 而不是重复正文；已有 inputs 需通过相同保密规则，Token/JWT/密钥/签名 URL 不入库。
Python 校验并生成 request_hash；出队前向 Java 请求本次有效授权，绑定 Run、身份、Capability、输入 revision/hash 与 lease_epoch。Java 重新检查会话/能力/文件权限，按需从已认证请求或受控在线会话取得业务 Token，仅通过内存传输；需要却无法取得则 waiting/authorization_required，用户重新认证后才继续。不需业务 Token 的能力仍须 Java 重新核权后签发 Run JWT；不能把入队时的授权快照当永久权限。
仍按当前聊天主链路划分读/执行控制权限，不恢复独立 run.steer 权限；鉴权签发、回调授权与业务 Token 生命周期需 Java 接入。可信资产解析后的无秘密 execution_snapshot 保存配置引用/摘要及部署版本；所需版本或工作区不可用时等待/失败，不能静默换新版本继续。

## 6. 恢复边界与事件投影

| 故障位置 | 重启后的动作 |
| --- | --- |
| 浏览器刷新或 Java 重启 | 从共享 Run/session 读取权威状态；按 event_id/run_sequence 重放输出增量。Java message 投影游标放在 Run；与 message 更新同事务推进，不依赖浏览器 SSE 存活 |
| Python 尚未领取或尚未发送 SDK | 原顺序和暂停状态保留；安全的文件准备可重新校验/下载，重新获取授权后继续；claim 不代表模型开始，SDK 发送前先持久化 sdk_started_at |
| SDK 已发送，尚无持久 result | 标 interrupted，保留部分输出、活动位并暂停队列；resolve_uncertainty 经 Java 核验旧进程停止及副作用处置证据后，Python 才清除活动位。resume_queue 此前返回 recovery_required；用户重新回答另建 Run，不能宣称从任意 SDK 工具继续 |
| SDK result 已持久化 | checkpoint=sdk_result_saved 与 result 事件原子保存；恢复进入 finalizing，仅补投影/成果交付，不再调用模型；已上传不再上传 |
| 引导发送过程中中断 | 发送前将 command=processing 持久化；无法证明未发送或已纳入则 unknown，绝不自动再次注入；源队列转引导保持非可执行状态 |
| 成果上传中断 | pending 可继续；uploading 转 unknown，须按 artifactId 向文件服务核对。只有上游支持幂等键或能确认未上传时才重试，否则人工处理 |

`runtime_event` 能补放已经提交的前端事件，但它不是完整 event sourcing：恢复时先读 Run/session 当前快照，再按游标补事件；超出保留窗口就重新取快照。事件不能重建 Python coroutine、内存邮箱、正在运行的子进程或外部副作用，也不能代替 SDK transcript。SDK 0.2.171 的 `SessionStore` 主会话 key 是 `(project_key, session_id)`，子代理另带 `subpath`；适配器内部可把省略的主会话 `subpath` 映射为空串，但传给 SDK 时必须按其 key 约定原样处理。`project_key/session_id` 唯一映射到 Runtime session，避免仅凭 conversation_id 猜 SDK key。

SDK 的 SessionStore 会先让 CLI 写本地 JSONL，再异步镜像；即使 `session_store_flush='eager'`，写入也不会阻塞流读取。SDK 在发出 Result 前会 flush 当前批次，但 append 失败最终通过 `MirrorError` 报告且不终止模型执行。因此 Runtime 必须单独持久化完整 Result/assistant 输出，并只在确认 transcript 含该完整轮次后，把 Run 的 `checkpoint_stage=sdk_result_saved`、`checkpoint_entry_uuid`、`transcript_sync_state=confirmed` 与 result 事件一起提交。镜像失败或无法确定时标记 unknown，阻止新 Worker 用该 transcript 恢复，先补齐本地 transcript 或进入 recovery_required。Transcript 含模型与工具对话内容，须隔离访问、加密和按会话保留，不进入公共 event/普通日志。

SDK `resume` 加载 transcript 可让新进程带历史上下文开始下一轮；`resume_session_at`/`resume_drops_turn` 与 fork 可选择历史分支、丢弃一轮，但不能恢复或继续原 Python Task、工具调用栈或半完成副作用。SDK 已启动且无已持久 Result 的 Run 必须标为 interrupted/unknown，暂停后续队列，不自动重放工具。用户确认处理不确定副作用并重新提交后，才可基于完整历史/安全分支发起新 Run。即使 transcript 可从 MySQL 恢复，session 仍需可用的持久 workspace；文件内容沿用现有持久文件服务，不放 MySQL 行内。
Run sequence 供现有 agent-events/v1 使用；session sequence 用于控制意图顺序。事件 ID/序号幂等回放前端内容，过期游标重新拉状态快照。命令/输出事件按保留窗口清理，SDK transcript 另按安全保留策略清理。
普通 Agent 首期只定义 input_prepared/sdk_result_saved 安全检查点。未来真正编排需要节点级输入、结果、重试和副作用幂等记录，选定编排执行器后再增加 step 表/其原生检查点；本提案不虚构通用 DAG，也不把普通 SDK tool 调用当可安全重跑节点。

## 7. 实施范围与验收门槛

需要 Java 改造入队事务、控制意图事件、临执行授权及 stale-streaming 修复；Python 将 RunStore/Actor 状态、事件与 SDK SessionStore 改为同库并实现恢复。**不是只改 Python 就能完整实现。**
此 DDL 面向 Java 主链路的共享部署，要求预先存在业务会话/user/assistant；通用 agent-run/v1 当前允许省略 businessSessionId、ID 可达256字符，不能用本表把通用解析器静默收窄。实施时共享部署须显式校验业务映射，未登记请求返回 business_record_required；切换前盘点实际直连调用方并完成接入，独立无业务记录调用不在本次共享表范围，不另造影子业务消息或双写兼容层。
共享模式上线应在维护窗口排空/停止旧 Run，结束在途引导/上传并处置 unknown，登记必要 SDK 工作区，再切换唯一状态来源；不长期双写 SQLite/MySQL，也不从旧 request_hash 伪造完整请求。历史消息照旧可读，切换方案须在实际实施时验收。
本次只提交设计和候选 DDL；现有 [API HTML](../python-api.html) 继续准确描述已实现行为。实现后再同步新增接口、状态、鉴权与重试示例，不能现在标成已支持。
必须验收：并发入队不重单、两 worker 不同跑一会话、暂停/编辑/取消与出队竞争、转引导各发送窗口崩溃、SDK 前后断点、上传 unknown、旧 epoch 回写被拒、Java 断线重放无重复/漏字、跨身份/权限撤销与持久化出口无凭据。静态 DDL 检查不算这些验收通过。
本次复核：SDK 0.2.171 类型与源码确认有 SessionStore/resume/fork API，当前 Runtime 未接 SessionStore；MySQL 适配器尚未实现或实机验证。安全恢复仅承诺未领取队列项和 transcript 已完整提交的 Result 边界；不承诺运行中工具事件级续跑。未对59执行候选 DDL。

| 要求 | 状态 | 依据 | 差距 |
| --- | --- | --- | --- |
| REQ-001 | 部分满足（方案覆盖，未实施验收） | 第5节：当前身份重新授权、三类凭据分离、仅内存按 MCP 注入 | Java 安全上下文来源、过期/撤销处理与全链路无泄漏须联调 |
| REQ-002 | 部分满足（方案覆盖，未实施验收） | 第2/5/6节：业务 Capability、服务端解析、运行关联、无秘密配置追溯、不虚构 Workflow | Java ACL、配置版本可恢复性、文件与进程隔离须独立验收 |
