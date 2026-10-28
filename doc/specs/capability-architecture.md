# Agent 代码架构与 Capability 规范

本文是 Agent 编写和修改 Runtime、能力资产及业务代码时的架构入口。字段细节以代码校验器为准，跨系统字段以 [Runtime 契约](ccsdk-runtime-interface.md) 为准。

## 运行链路

```text
前端 → Java 授权并选择 Capability → Python Runtime 装配本轮资产
    → Claude Agent SDK loop → Tool / Capability Operation
    → 通用 Service、数据库或远端 MCP → 结果与 Artifact 经 SSE/文件接口返回
```

- Java 管业务身份、租户、Capability/文件授权、会话和消息；Python 只执行可信服务端解析后的能力。
- `runtime/capabilities.py` 解析能力声明；`runtime/config.py` 装配数据、工具和提示词；`runtime/prompt_assembly.py` 是提示词唯一编译入口。
- `runtime/tool_catalog.py` 读取可信 Tool 声明，`runtime/tool_registry.py` 使用固定 Provider 装配工具。`capability_packs/registry.py` 只在执行时加载所选源码包，`runtime/capability_operations.py` 将登记操作适配成 Agent Tool。
- Run 仍由 Agent loop 驱动。`execution.mode=direct` 限制可用执行能力，不固定模型的调用顺序，也不保证某个 Tool 一定被调用。

## 职责与代码位置

| 内容 | 权威位置 | 用途 |
| --- | --- | --- |
| Capability 声明及入口规则 | `.claude/capabilities/<ref>/capability.json`、`CAPABILITY.md` | 定义业务入口、工具/数据/模板引用和本能力规则 |
| 能力专属指引 | `.claude/capabilities/<ref>/instructions/` | 多段或较长的能力规则；必须由 `instructionRefs` 显式引用 |
| 可复用方法 | `.claude/skills/<ref>/{skill.json,SKILL.md}` | 适用条件明确、有可复用步骤和可核验产出的 Agent 方法 |
| 公共提示词 | `.claude/prompts/` | `system.md` 是共享 SDK 底座；`base.md`、`date.md`、`direct.md`、`no-web.md` 等放公共执行规则，不放单个业务口径 |
| 模板和模板指南 | `.claude/capabilities/<ref>/templates/<templateRef>/` | `template.json` 绑定 DOCX、指南和数据来源角色；模板只写模板特定要求 |
| Tool 声明及工具指引 | `.claude/tools/<ref>/tool.json`、`TOOL.md`（有指引时） | 操作 Schema、分类、MCP 传输/凭据目标及 `instructionRefs` |
| 数据库语义与查询资产 | `.claude/databases/<sourceRef>/` | `source.json`、域 schema、metrics YAML 和 semantics 文档 |
| 通用 Runtime/Tool 实现 | `python/runtime/`、`python/tools/`、`python/data_access/` | 能力无关的装配、SDK、MCP/文件/文档/数据操作 |
| 能力专属可信代码 | `python/capability_packs/<ref>/` | `pack.json` 登记 Operation；`operations.py` 实现本能力业务动作 |
| 部署连接和凭据 | `config/`、环境变量或 Secret Manager | 只保存运行配置；不把秘密复制进 Prompt、业务资产或日志 |

## Capability 组成规则

- `capability.json` 是服务端声明，不是 Python 入口。`toolRefs` 选择 Agent 可见 Tool；`requiredToolRefs` 是必需子集。`data.sourceRefs` 声明本能力可申请的数据来源；`templates` 只登记可选模板。发现或声明资产本身不授予 Java 业务权限。
- `skillRefs` 选择可复用 Skill；`requiredSkillRefs` 是必载子集。按需 Skill 只注入说明和受控读取路径。Skill 不能自行增加能力未声明的 Tool。
- 有代码时，`operationRefs` 选择 `pack.json` 已登记的操作；`serviceRefs` 选择仅供这些操作内部使用的 Service。Service 不因被引用就成为 Agent Tool。
- Agent 可见的 MCP 操作从 Agent 视角就是 Tool；MCP Server 是承载一组操作的协议端点。Provider 只做通用 Runtime 装配，不按客户/业务场景新增 Provider。
- Service 只在需要共享实现、状态或受控上游调用时建立，不要求每个 Tool 配一个 Service。通用文档、文件、图表和数据操作留在共享 Runtime；业务差异留在 Capability 规则、数据资产或模板。
- 仅提示词、口径、数据来源或模板不同，复用现有 Capability 组成，不复制能力代码。只有确有独立业务算法或动作时才添加能力代码包；不要为了目录完整创建空包。

## 提示词归属

1. `CAPABILITY.md` 写该业务入口必须遵守的规则与工作方式；能力特有的长指引放同目录并通过 `instructionRefs` 引用。
2. `.claude/prompts/` 只放跨能力公共规则。模板特定写法放模板目录的指南，指标定义、SQL 与数据关系放数据库资产，工具使用说明放 Tool 的 `TOOL.md`。
3. 只有具备复用方法和验收产出的内容才建 Skill；几条提醒、单个工具说明或模板说明不单建 Skill。
4. 不在 Runtime、Tool 或业务代码里私自拼第二套系统提示词；修改资产后检查管理预览与执行使用的同一编译结果。`not_for_model` 材料不得进入模型提示词。

## 业务代码与执行边界

- 只有能力专属的确定性业务动作放进 `python/capability_packs/<ref>/operations.py`；公共实现仍留在 `python/tools/`、`python/data_access/` 或已有 Service。不要把业务专用规则搬进通用 Provider。
- 每个 Operation 在 `pack.json` 声明输入/输出 Schema 和 handler。Agent 通过 `operationRefs` 看到这些动作，并仍自行决定是否、何时调用；代码可以确定动作内部步骤，提示词不能保证模型必定触发。
- 当前没有通用 Workflow/DAG 执行器。若业务要求由系统保证固定顺序或必定启动，单写 Prompt 或 Operation Tool 不足以保证；需另行设计服务端受控入口，不得声称现有 `direct` 已提供该保证。
- 代码包是随 Runtime 部署的可信 Python 代码，拥有 Worker 进程权限；不是上传式插件或沙箱。能力/Prompt/数据库资产不得指定模块路径、任意 Python 入口或动态 Provider。代码变更随部署并重启 Worker 生效。
- Operation 只通过 Runtime 提供的本轮 `CapabilityContext` 使用数据、文档、Artifact 和已选 Service；不要自行读取全局环境中的业务 Token、创建未登记 MCP，或绕过通用执行器访问数据库。

## 修改前后检查

- 先确认职责归属和现有复用资产，再选择修改 Prompt、Capability 声明、Tool、数据资产或能力代码；避免在多处复制同一规则。
- 涉及方案或结构时逐条检查 [REQ-001/002](engineering-requirements.md)，明确状态、代码/测试依据和未验收差距；Java 授权、生产撤销及真实业务质量不能由 Python 单测代替。
- 代码变更使用 `npm test`；文档变更检查相对链接、字段名与资产路径。跨系统字段和数据连接分别以 [Runtime 契约](ccsdk-runtime-interface.md)、[数据资产规范](data-source-connections.md) 为准。
