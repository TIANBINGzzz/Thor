# ADR-037: 能力拥有业务 Operation，Tool 仅适配

| 字段 | 内容 |
| --- | --- |
| 决策日期 | 2026-10-26 |
| 决策状态 | 已采纳 |
| 实现状态 | Python 可信代码装配、静态发现及逐轮工具边界已接入；校园资源与撰写模板归入能力包，能力及 Skill 正文仍由 MySQL 提供 |
| 最近核对 | 2026-11-20 |
| 替代的旧 ADR | 无；保留 029 的自主撰写与 036 的提示词归属 |
| 被哪份 ADR 替代 | 无 |

## 背景

业务动作若继续堆在通用 Tool 或按场景增加 Provider，能力配置与实现就会分离，固定代码步骤也缺少明确入口。

## 决策

- 业务实现及 Capability 专属部署资源归 `python/capability_packs/<capabilityRef>/`，`pack.json` 登记输入/输出 Schema 和处理器，`operations.py` 提供同步或异步动作；模板放 `templates/`，可复用 Skill 的本地审阅副本放 `skills/<ref>/`。能力正文与 Skill 正文由 MySQL 提供，是运行时唯一可信源；本地导出不参与提示词装配或 fallback。
- 源码能力显式选择同名包的 `operationRefs`；Worker 统一适配为 MCP Tool，复用本轮 Service、Schema 校验、授权 Hook 和事件。确定步骤写在 Operation 内，Agent 决定调用时机；提示词不保证必定调用，不引入 Workflow/DAG。
- 目录发现只读取代码包声明，不 import 业务代码；只有源码能力可选择代码包，不提供上传代码或在线配置管理接口。
- 公开 Capability 目录仍以 MySQL 的启用记录为准；本地代码包存在或可静态发现，不自动公开或授权能力。
- 代码包按 Worker 加载并缓存，部署变更通过重启生效；不在线换码或保存源码版本。Operation 不跨轮复用上下文，收尾超时退役 Worker。

## 后果与验证

可信能力代码拥有 Worker 进程权限；Context 门面不构成沙箱。校园 Operation、词表及配置资源和 document-writing 模板现在分别位于对应能力包。数据库导出脚本仅为 Git 审阅生成 Capability/Skill 文本快照，不写数据库；Runtime 仍从 MySQL 装配，公开目录仍按 MySQL 启用记录返回。Agent 只看到 `capability_ops` 中的已选 Operation；普通对话、撰写、图表、图像和双高问数没有独立业务代码，不创建空代码包。本地回归覆盖输入输出 Schema、静态发现、数据 Service 与 Tool 解耦、取消收尾和真实 SDK CLI 同会话切换/撤销，模型使用本地协议桩，不能代替业务验收或生产隔离。

## 工程要求检查

| 要求 | 状态 | 依据与差距 |
| --- | --- | --- |
| REQ-001 | 部分满足 | Operation 不接收业务 Token，公共 MCP 沿原规则逐轮注入并清理；Java Token 来源、生产撤销及日志全链路未验收 |
| REQ-002 | 部分满足 | Capability 仍为唯一入口，校园代码及 Operation 由可信声明选取，目录发现不导入代码；Java ACL、完整源码版本追溯及真实业务质量未验收 |
