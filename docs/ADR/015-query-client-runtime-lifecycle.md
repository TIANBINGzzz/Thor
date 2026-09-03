# ADR-015: Query 与 ClaudeSDKClient 生命周期

日期: 2026-09-03
决策状态: 已采纳
实现状态: 部分实现
替代: 无
被替代: 无

## 背景

普通对话只需要一次执行后释放 Runtime；撰写和交互式 Workflow 需要连续消息、
实时中断和较长的工具生命周期。Claude Session、SDK Client、Python Task 和
浏览器连接具有不同生命周期，混用会造成跨 Task 操作 Client 和错误恢复承诺。

## 决策

普通对话、问数和一次性任务默认使用 `query()`。每个 `runId` 创建独立 asyncio
Task；下一轮可以用 `ClaudeAgentOptions(resume=session_id)` 在新 Task 中恢复历史。

撰写 Skill 和长任务使用 `ClaudeSDKClient`。每个活跃 Claude Session 只有一个
`SessionActor`，由唯一长期 Task 创建、连接、查询、接收、中断和断开 Client。
HTTP/SSE/WebSocket 只能向 Actor 的普通队列和高优先级控制队列投递消息。

浏览器断线只取消订阅。Actor 在 Run 结束后按 idle TTL 销毁；平台保存
`runtimeSessionRef`、transcript、Run/Event、Workspace 和 Artifact。新 Actor 可用
`resume` 恢复 Claude 上下文，但不恢复旧 Task、工具/MCP 进程或内存状态。

一个 Client 不得切换承载多个用户 Session，也不得用全局 Lock 代替单 owner Actor。
能力或权限切换时创建新 Runtime Session，并通过 Java 的审计摘要交接上下文。

## 后果

### 好处

- 默认对话资源占用小，撰写任务具备连续交互和原生中断能力。
- SSE 重连、Runtime 重建和 Claude Session 恢复的边界明确。
- Client、Workspace、MCP 和凭据始终归属单一租户会话。

### 代价与风险

- Client 模式需要 Actor 路由、idle TTL、租约和连接级 Token 更新策略。
- Worker 中途死亡不能续跑原任务；只能新建 Run，并按持久状态决定是否 resume。
