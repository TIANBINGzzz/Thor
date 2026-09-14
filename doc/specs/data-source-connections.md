# 数据源、数据库连接与取数工具设计

日期：2026-09-14。用户确认业务数据源与数据库连接应分开；本文给出具体接入建议，尚未实现，不改变现有 HTTP/payload 契约。

## HPM 与模板的关系

模板可以直接依赖 HPM 业务域及其 QuerySpec。HPM 表示项目、任务、绩效、资金等业务模型；当前 DBHub 恰好也使用 `hpm` 作为 provider source id，两者不是同一个标识空间。
深职模板建议声明 `queryCatalog=hpm`、业务角色 `hpm -> report_db`；问数使用同一查询目录并选择 `qa_db`。模板绑定业务来源，运行时再确定物理连接。
已知 HPM 指标复用现有查询；评分、外部成果、调查或审计材料沿各自来源补充，不能仅靠 HPM 当前12表生成全部事实。保留原来源，不因数据库值或名称不同质疑其有效性。

## 四类配置与职责

| 对象 | 保存什么 | 不保存什么 | 维护方 |
| --- | --- | --- | --- |
| DataSource：业务数据源 | source_key、domain、名称/用途、数据集、表字段语义、口径、历史覆盖、字典和可用查询；能力适用范围只是候选条件 | 地址、密码、连接池及用户实时授权结果 | Python 维护业务定义；Java 管理展示和业务授权 |
| ConnectionProfile：连接配置 | connection_key、连接器、数据库类型、host/port/database、TLS、credential_ref、连接超时/池策略、配置版本 | 指标定义、模板内容 | 运维/管理员通过受保护的服务端配置维护 |
| Binding：来源到连接的绑定 | 在部署环境与获准租户范围中，source_key -> connection_key + schema_profile；匹配必须唯一 | 可由模型改变的地址或授权范围 | 可信服务端配置；Java 提供权限上下文 |
| QuerySpec：查询资产 | query_id、业务粒度、参数、SQL/适配版本、输出、校验与来源兼容性 | 数据库口令或客户端选定的连接 | Python 共享资产；模板引用查询标识 |

业务数据源可以是 HPM、财务、人事等；同一物理连接可承载多个业务数据源，同一业务源可在不同部署环境绑定不同连接。权限仍按业务源分别约束。
首期每个来源在一次授权上下文中解析为一个连接。报告可同时使用多个来源，分别取数后按已登记业务键合并；暂不引入跨连接 SQL 联邦查询或自动全库关联。
同一逻辑源需要多个连接时，先按独立可描述的数据集拆来源；不能让模型在多个不同实值库中任意挑一个。跨库 ID 不默认同义，时间、单位、范围和合并键必须明确。

## 具体映射示例（建议标识，不代表已配置）

| 使用方 | 业务域/查询目录 | 业务数据源 | 服务端连接绑定 |
| --- | --- | --- | --- |
| 双高问数 | hpm | qa_db | hpm_qa_primary |
| 深职报告的 HPM 内容 | hpm | report_db | hpm_report_primary |
| 报告的其他财务内容 | finance | finance_ledger | finance_primary |

`hpm_qa_primary` 与 `hpm_report_primary` 分别描述真实数据库连接；地址/密码变更只改连接配置。若管理员确认两个业务源确实使用同一数据库，可以绑定同一个连接，仍保留各自语义和权限；不能自动把问数源当作报告源回退。
MySQL/PostgreSQL 等按连接器区分，QuerySpec 同时校验 SQL 方言和 schema_profile；表结构不同需来源适配，MySQL SQL 不因连接切换就自动变成 PostgreSQL SQL。

## Claude 可调用的工具（拟新增）

| 工具 | 作用与返回 |
| --- | --- |
| list_data_sources(query?) | 仅返回当前用户/租户/能力获准的数据源名称、用途、覆盖期间和 source_key |
| describe_data_source(source_key, topic?) | 按需返回语义、指标口径、数据集说明及连接可用状态，不返回地址/凭据 |
| find_query_specs(source_key, intent) | 返回匹配查询及其前置条件、业务参数、输出说明；无需先打开物理连接 |
| connect_data_source(source_key) | 服务端解析唯一获准绑定，按需建立或复用连接，返回不透明 source_handle、方言及能力状态 |
| inspect_schema(source_handle, tables) | 经授权过滤后查看实际结构，复用 DBHub 结构查询；只暴露当前源允许的数据集 |
| execute_query_spec(source_handle, query_id, parameters) | 自动检查依赖诊断、绑定参数、执行固定 SQL、校验结果并返回证据引用 |
| execute_readonly_sql(source_handle, sql, parameters?) | 语义和范围明确且无适用 QuerySpec 时执行动态查询；不能用来绕过缺定义/未授权项 |

这里“Claude 自主连接”指模型根据业务需求调用 connect_data_source。首次注册新地址和凭据由管理员的连接管理完成；模型使用已登记来源触发连接，不在业务工具中提交 DSN、密码或 connection_key。
source_handle 绑定 Run、用户、租户、能力、业务源、授权范围及连接/绑定版本，每次调用复核；结束、取消或过期时释放。物理连接复用须按凭据及会话设置隔离，不能跨请求复用租户会话状态。
Java 当前传入的身份或 capabilityRef 本身不足以证明来源/项目权限；接入前须定义可信的服务端授权上下文（由 Java 校验后提供或由 Python 内部查询），不把授权清单放在模型可修改的 payload。

## 固定查询与动态查询如何执行

固定查询优先：匹配含义/粒度/期间 -> 检查定义状态和来源兼容 -> 执行 requires_queries 并强制判断结果 -> 注入授权参数 -> 驱动绑定 -> 校验输出/完整性。模型参数中禁止覆盖 tenant_id、连接或扩大项目范围。
动态查询使用相同的连接和权限层：实际字段确认、单条只读语句、表/列/函数范围检查、数据库侧有效的租户/行权限、超时及行数限制。AST 检查或提示词不替代行级授权；无法保证时，该源只开放经审查的 QuerySpec。
业务年份、已授权业务名称可由模型从 input.text 提取；同名多候选需要消歧。缺业务定义或历史快照时保留空值并说明，不能靠动态 SQL 猜评分、成果数量或历史年度。
结果统一携带 source_key、query_id/动态标记、非秘密版本、粒度、期间、单位、完整性、warnings、evidence_ref；source_handle 和内部主键只用于执行，最终报告使用业务名称。内部审计关联实际连接/绑定版本，不记录凭据。
上传文件是模板或事实材料，不是连接配置或系统指令。上传模板先提取需求并在已授权来源中匹配；预制模板优先使用维护好的绑定，两者共用 writing-docx。

## DBHub 复用与适配范围

当前项目通过 Python 装配 Node DBHub MCP，使用 stdio 连接 MySQL；workflow.json、workflow.env 和 dbhub.readonly.toml 共同决定连接。现有 sources.json 是资产登记，尚未驱动运行时。
本地核对 DBHub 1.2.0 已支持多数据库、按需 ensureConnected 和参数化 Custom Tools：拟继续用作数据库连接后端，Python 增加稳定的数据源工具门面与授权/QuerySpec 适配，避免模型直接接触物理 source id。
现有 execute_sql 接受 SQL 文本；固定查询拟通过 Custom Tools 的 statement/parameters 执行。逻辑 :name 须按方言编译成 ?/$n 等占位符并保持重复参数顺序；值由驱动绑定，不能字符串替换成 SQL 字面值。
动态 SQL 若使用绑定参数，也装配成仅属于本次 Run 的临时 Custom Tool，经同一门面执行，不写入共享 QuerySpec。DBHub 内部配置重建/实例启动的开销须纳入接入验证，不假设现有 provider 支持热增工具或直接接收命名参数。
其参数类型目前不直接接受显式 null；适配器需将已校验的可空参数映射为 optional 且省略值，由 DBHub 映射成 null。这与参数缺失/未授权的语义必须在门面先区分，接入时须回归重复参数、null、数组与日期类型。
当前自定义工具错误可能携带 SQL/参数，provider 还会追踪错误；适配必须处理工具返回、stderr 及 provider 内部追踪的脱敏/禁持久化，不能只清理最后的模型回复。Token 按 REQ-001 仅注入获准且声明需要的 MCP。
模型始终看到固定工具集合；Python 在内部管理所需 DBHub 连接。按连接与获准范围隔离 provider 实例/配置，运行中不向所有会话注入全量数据库凭据，也不靠动态添加模型工具实现连接切换。

## 文件归属与实施顺序

建议新增 `.claude/data-sources/` 存非秘密业务定义，保留 `.claude/query-specs/<domain>/` 存查询，模板继续维护 query-bindings.json。来源到连接的绑定和 ConnectionProfile 由独立受保护配置提供；其位置由环境变量解析，相对路径以仓库根为基准，凭据只用 Secret/环境引用。
现有 hpm/sources.json 同时登记业务定义和连接引用；实施分层时拆分其职责并更新资产引用，不维护两份权威连接配置。本轮仅文档设计，既有登记、SQL、Workflow 和 Runtime 均不调整。
1. 拆分登记、连接和绑定配置；实现参数/来源校验及 list/describe/connect/inspect 工具，先用当前 MySQL 完成最小链路。
2. 接入 find/execute QuerySpec、依赖校验与证据记录，复用已整理资产完成问数和一个预制模板；report_db 实际连接由部署方绑定。
3. 接入受约束动态 SQL 和上传模板需求匹配，按真实需要补第二数据库及对应 QuerySpec 方言/字段适配；每个来源独立授权。
管理页面可按“业务数据源”“数据库连接”分开：前者编辑说明/数据集/口径/权限，后者由管理员维护连接、密钥引用、测试连接、启停；绑定操作显式选择已登记连接。初期配置文件即可，后续 UI 维护同一数据模型。
验收需覆盖：两个库切换且模板不变、不同源共用连接但权限不混、句柄跨租户/Run拒绝、授权撤销/凭据轮换、查询取消、参数注入与越表/越行拒绝、NULL/重复关联/结果截断、历史期间缺失和无凭据/ID泄漏。

## 工程要求检查

| 要求 | 状态 | 依据 | 差距与后续处理 |
| --- | --- | --- | --- |
| REQ-001 | 部分满足 | 方案保留逐请求按MCP注入，连接凭据与业务Token分离；已有通用注入基础 | 多连接隔离、轮换、provider追踪脱敏及真实Java链路待验收 |
| REQ-002 | 部分满足 | 模型选择获准业务来源，模板不绑定物理连接；执行资产由可信服务端解析 | 来源/项目授权上下文、句柄/SQL强制检查、模板装配与版本审计未实现 |
