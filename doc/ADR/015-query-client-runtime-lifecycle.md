# ADR-015: Query 与 ClaudeSDKClient 生命周期

| 字段 | 内容 |
| --- | --- |
| 决策日期 | 2026-09-03 |
| 决策状态 | 已采纳 |
| 实现状态 | 部分实现 |
| 最近核对 | 2026-09-07 |
| 替代的旧 ADR | 无 |
| 被哪份 ADR 替代 | 无 |

## 背景

一次性任务与连续交互需要不同执行生命周期；混淆 Claude Session、Client、Task、Run 和浏览器连接会导致跨 Task 调用或错误恢复承诺。

## 决策

- 普通对话、问数和一次性任务默认 query()，每个 runId 独立 Task；下一轮在新 Task 用 resume=session_id 恢复历史。
- 撰写和长任务用 ClaudeSDKClient；每个活跃 Claude Session 只有一个 SessionActor，由唯一长期 Task 驱动 Client 的创建、连接、查询、接收、中断和断开。
- HTTP/SSE/WebSocket 只向 Actor 投递普通任务和高优先级控制命令；浏览器断线仅取消订阅，Run 结束后按 idle TTL 回收 Actor。
- 平台保存 runtimeSessionRef、transcript、Run/Event、Workspace 和 Artifact；新 Actor 的 resume 只恢复上下文，不恢复旧 Task、工具/MCP 进程或内存。
- Client 不跨用户 Session 复用，不以全局 Lock 代替 owner；能力或权限切换新建 Runtime Session，由 Java 审计摘要交接上下文。

## 实现证据与差距

- 代码：[session_actor.py](../../python/runtime/session_actor.py) 管理队列/TTL/会话归属，[process.py](../../python/runtime/process.py) 驱动持久 Worker，[claude_sdk.py](../../python/runtime/claude_sdk.py) 检查 Client Task 归属。
- 验证：[test_session_actor.py](../../python/tests/test_session_actor.py)、[test_claude_sdk.py](../../python/tests/test_claude_sdk.py) 的串行、超时、中断、TTL、凭据指纹及跨 Task 限制随本次 Python 测试通过。
- 差距：跨实例租约、transcript 持久恢复、运行中授权撤销和 Java 摘要交接未完成端到端验收；测试使用替身，不代表真实 Provider 长会话已验收。

## 后果

- 好处：一次性任务资源易释放，长任务可持续交互，恢复边界清楚。
- 代价：维护 Actor 路由、控制优先级、TTL、凭据更新和生产租约。
- 风险：Worker 死亡不能原位续跑；新 Run 是否 resume 必须依据持久状态和当前权限。

## 工程要求检查

| 要求 | 状态 | 依据 | 差距与后续处理 |
| --- | --- | --- | --- |
| REQ-001 | 部分满足 | 凭据指纹变化可替换空闲 Actor且有测试 | 运行中 Token 过期/撤销处理与真实隔离验收仍缺。 |
| REQ-002 | 部分满足 | 内部受控配置驱动 Actor | 生产能力授权、配置追溯及 Capability 解耦仍由控制面闭环。 |

## 状态变更记录

| 日期 | 决策状态 | 实现状态 | 说明 |
| --- | --- | --- | --- |
| 2026-09-07 | 已采纳 | 部分实现 | 补记当前核对结果、证据与差距；不追补未知的历史状态日期。 |
