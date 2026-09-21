# ADR-033: 业务会话跨能力连续性

| 字段 | 内容 |
| --- | --- |
| 决策日期 | 2026-09-21 |
| 决策状态 | 已采纳 |
| 实现状态 | Python已验证；本次不修改前端及Java |
| 最近核对 | 2026-09-21 |
| 替代的旧 ADR | 替代 ADR-014、ADR-015 的执行模式选择及跨能力历史交接；旧正文见[历史索引](README.md#已移除的正文) |
| 被哪份 ADR 替代 | 无 |

## 背景与决策
- Python保持本轮capabilityRef和JWT契约，省略能力仍为conversation；前端选择的保存与恢复不在本次修改范围。
- 有businessSessionId的Run统一使用Client，按tenant、sub和业务会话隔离SDK历史；无业务会话的请求保留配置指定的执行模式。
- 同会话的配置/凭据变更进入同一串行队列，重建Worker加载本轮工具与规则并resume原SDK历史，不继承旧工具授权。
- 每个 SessionActor 由唯一长期 Task 驱动 Client；HTTP/SSE 只投递执行和控制，断开订阅不取消 Run。空闲回收后 resume 仅恢复历史，不恢复旧 Task、工具进程或内存。
- Python管理SDK历史和续接；Java只保存业务元数据、鉴权和转发，不承担AI摘要生成。

## 证据与后果
- Python全量268项测试通过，覆盖身份隔离、跨能力排队、配置/凭据重建、空闲回收及RunStore恢复。
- 真实模型完成conversation→image-generation→document-writing→conversation记忆验证，另一会话隔离和进程重启恢复通过。
- 历史连续减少重复输入；Client占用和切换重建成本增加。历史保留之前已提供的内容，工具权限收回不等于擦除历史。
- 恢复须保留RunStore和SDK transcript；容器沿用持久化的.scribe-runs。多实例同会话租约及Java生产授权未验收，resume不回滚工具副作用。

| 要求 | 状态 | 依据与差距 |
| --- | --- | --- |
| REQ-001 | 部分满足 | 凭据按Run装配、切换排队、无凭据持久化；活动Run的授权撤销仍依赖控制面取消 |
| REQ-002 | 部分满足 | JWT仍绑定本轮能力，历史只按同身份同会话共享；前端选择持久化及Java生产ACL待联调 |

| 日期 | 决策状态 | 实现状态 | 说明 |
| --- | --- | --- | --- |
| 2026-09-21 | 已采纳 | Python已验证 | 实现与验证范围见上文 |
