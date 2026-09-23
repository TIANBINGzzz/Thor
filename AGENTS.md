# 开发约定

本文件是项目唯一的开发指引。先读 [ARCHITECTURE.md](ARCHITECTURE.md)，再按任务读取所需契约或执行资产；不默认加载全部文档。

## 工作方式

- 使用中文维护项目说明和必要注释；接口、核心逻辑及非显然分支说明约束、失败处理或原因，不逐行翻译代码。
- 采用能满足需求的最简单长期方案，保持模块化；先检查现有实现和依赖，优先复用成熟产品模式及有人维护的库。
- 先跑通最小端到端链路再扩展，不以未完成的抽象替换可用功能；不做预防性配置层，不保留过时兼容层、migration 或 fallback。
- 新增资产前核对复用方式、独立职责、实际调用方和验收方式；删除前核对引用，必要规则先合并。
- 每次改动后执行相应检查并自动创建本地 Git 提交，方便回滚；只提交本任务内容，不覆盖用户改动。
- 新增或修改方案须逐条检查 [工程要求](doc/specs/engineering-requirements.md)，总结列出编号、状态、依据及差距；不适用也说明原因，不把设计符合或测试存在当作验收通过。

## 执行资产边界

- Python 管理 Runtime、SDK 和通用工具；`.claude/` 管理执行配置与业务知识。Workflow 专属表范围、口径及模板不得写进通用 Python。
- Capability 是业务入口，内部资产和权限由可信服务端装配，遵循 [REQ-002](doc/specs/engineering-requirements.md#req-002前端触发-capability执行资产保持内部化)。只有执行步骤、审批、并行、重试或外部副作用确实不同才拆 Workflow。
- Skill 须有可复用方法、适用条件和可验证产出；单工具包装、几条提醒和模板说明不单建 Skill。单流程规则留在其目录，共同规则只维护一份。
- 产品规则通过 `workflow.json` 的 `documents`/`skills`、Capability 内部 `capability.json.documents`、所选 `template.json.assets` 和数据库 `source.json.domains` 显式加载，不依赖开发指引自动发现；未登记及 `not_for_model` 材料不进入 Prompt。
- 数据库知识按来源集中，指标含义与 SQL 不复制到模板。未知定义不得编造 SQL，`pending`、`blocked`、`needs_definition` 不因目录整理自动升级；详见 [数据契约](doc/specs/data-source-connections.md)。
- 文稿由 Agent 依据共同规则、所选指南及授权资料自主规划、取证、撰写和核验；OfficeCLI 原生 MCP 编辑，LibreOffice/PDFium 渲染及阅读。不得新增位置地图、固定取数计划、报告状态机或自研编辑层。
- 上传模板作结构和样式参考生成新稿；预制与上传两类均须核验证据、目录和成稿，不用默认值掩盖缺口。执行规则以 [共同规则](.claude/workflows/writing-docx/instructions.md) 为准。
- 当前未定义项目子代理。仅记录 `.claude/agents/*.md` 中实际存在的名称、职责和场景；新增或删除时同步本节，不臆测代理能力。

## 数据、凭据与验证

- Workflow 私有环境使用同目录、被忽略的 `workflow.env`；数据库连接及策略只放部署侧 `databases.json`，配置基准目录见 [配置字段](config/README.md)。
- 通用密钥放 `.env` 或 Secret Manager，不写入代码、执行资产、Prompt、日志或报告。仅 `config/databases.json` 经用户授权随本版私有源码和镜像交付，范围见 [ADR-028](doc/ADR/028-bundled-database-config.md)。
- 业务 Token、Run JWT 和模型密钥用途分离；业务 Token 仅按 [REQ-001](doc/specs/engineering-requirements.md#req-001业务-token-透传与按-mcp-注入) 注入选定 MCP，不修改全局环境或跨 Run 复用凭据。
- 真实问数使用临时进程配置和只读查询，与独立基准对照；真实租户值、内部 ID、原始结果及私密验证材料留在忽略目录，不提交 Git。
- DBProcessing 的 `doc/model_context` 是双高问数外部语义来源；只提炼硬约束、业务口径及必要字段，`not_for_model` 中的 DDL、样例值、真实 ID 和人工快照不注入 Prompt。
- 普通 Agent 的 `bypassPermissions`、路径约定和容器不构成生产多租户沙箱。真实 Java 授权、撤销、文件/进程/网络/凭据隔离仍须独立验收。
- Python 回归使用 `npm test`；部署检查和真实链路入口见 [部署说明](deploy/README.md)。仅文档改动按引用、契约示例及涉及资产核验，不把静态检查当作真实业务验收。

## 文档规范

- `README.md` 只写项目描述和功能；`ARCHITECTURE.md` 只保留既定九部分的职责、边界和查找入口。结构变化更新架构，不向 README 堆实现细节。
- 仅保留跨系统契约、业务口径、重要决策及必要运维信息。代码、类型、配置和测试可直接表达的事实不另写教程、代码抄本或逐次工作报告。
- 每条规则只有一个权威来源，其他文档使用链接；过期或重复说明合并后删除，历史从 Git 查找，不另建归档副本。
- 不写超过 100 行的详细教程、长篇使用/排障指南，不在 `doc/` 根目录新增冗长 Markdown。字段参考和模板业务知识按职责集中，不靠拆成大量小文件规避精简。
- ADR 放 `doc/ADR/NNN-kebab-case-title.md`，按 [模板](doc/ADR/template.md) 写背景、决策和后果，优先 20-30 行、最多 50 行；决策状态与实现状态分开，替代及删除规则见 [ADR 索引](doc/ADR/README.md)。
- 模板指南、指标定义和来源核验记录是必要业务知识；执行规则留在 `.claude/`，`doc/verification/` 只保留必要证据、未决口径和验收边界，不自动注入模型。
- 临时计划、原始日志和测试材料放忽略的 `scratch/`，不提交 Git。`FUTURE-IDEAS.not-for-model.md` 只保存人工想法，仅在用户要求查看或维护时读取，不据此自行实施。

## 可部署路径

- 代码、配置、资产和文档不硬编码宿主机盘符、UNC 或 Linux/macOS 主机目录。项目内用仓库相对路径，运行时由 `Path(__file__)`、配置或环境变量解析。
- 部署目录、锁文件和远端发布路径用参数或环境变量，并说明相对路径基准；运行时解析成绝对路径允许。文件引用遵循 [Runtime 文件契约](doc/specs/ccsdk-runtime-interface.md#8-file-broker-模块)。
- 固定容器路径仅按明确的容器契约使用；系统解释器入口与 HTTP 路由不是宿主机路径。外部项目或用户文件只记录项目名、文件名和相对位置。
