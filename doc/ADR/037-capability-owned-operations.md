# ADR-037: 能力拥有业务 Operation，Tool 仅适配

| 字段 | 内容 |
| --- | --- |
| 决策日期 | 2026-10-26 |
| 决策状态 | 已采纳 |
| 实现状态 | Python 可信代码装配、静态预览及逐轮工具边界已接入；既有业务不迁移 |
| 最近核对 | 2026-10-26 |
| 替代的旧 ADR | 无；保留 029 的自主撰写与 036 的提示词归属 |
| 被哪份 ADR 替代 | 无 |

## 背景

业务动作若继续堆在通用 Tool 或按场景增加 Provider，能力配置与实现就会分离，固定代码步骤也缺少明确入口。

## 决策

- 业务实现归 `python/capability_packs/<capabilityRef>/`，`pack.json` 登记输入/输出 Schema 和处理器，`operations.py` 提供同步或异步动作；有内部复用需求才建 Service。知识、模板、Prompt 仍归 `.claude/`，不将数据库口径写进通用 Python。
- 源码能力显式选择同名包的 `operationRefs`；Worker 统一适配为 MCP Tool，复用本轮 Service、Schema 校验、授权 Hook 和事件。确定步骤写在 Operation 内，Agent 决定调用时机；提示词不保证必定调用，不引入 Workflow/DAG。
- 目录发现及有效内容预览不 import 业务代码；管理 API 只组合既有声明资产，不能上传 Python、指定模块或调用代码包。
- 代码包按进程加载一次，指纹检测准备和加载间变更，代码发版须重启；不保存源码版本、不热换。Operation 不跨轮复用上下文，收尾超时退役 Worker。

## 后果与验证

可信能力代码拥有 Worker 进程权限；Context 门面不构成沙箱。现有校园问数等不迁移；本地回归覆盖输入输出、静态预览、数据 Service 与 Tool 解耦、取消收尾和真实 SDK CLI 同会话切换/撤销，模型使用本地协议桩，不能代替业务验收或生产隔离。

## 工程要求检查

| 要求 | 状态 | 依据与差距 |
| --- | --- | --- |
| REQ-001 | 部分满足 | Operation 不接收业务 Token，公共 MCP 沿原规则逐轮注入并清理；Java Token 来源、生产撤销及日志全链路未验收 |
| REQ-002 | 部分满足 | Capability 仍为唯一入口，代码及操作由可信声明选取；Java ACL、完整源码版本追溯及真实业务质量未验收 |
