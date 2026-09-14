# 数据源管理与数据库工具设计

2026-09-14。方案一细化设计，尚未实现；现有 HTTP、MCP、Workflow 和部署行为不变。模板执行见[批量取数方案](template-batch-data-plan.md)，决策见 [ADR-021](../ADR/021-template-batch-data-plan.md)。所有新增字段/工具/命令均为拟议契约。

## 职责与执行后端

Java 管理身份、Capability、模板/数据源/项目 ACL；Python 维护语义、查询、模板绑定并执行取数；管理员维护连接与密钥。问数和撰写共用 `data` MCP，模板仍使用 `writing-docx`。
模型只传业务来源与查询参数；服务端按 Run 授权解析唯一连接并懒连接，连接句柄仅内部持有，无需模型先调用 connect。同一逻辑来源可按部署/租户绑定不同连接；同一连接可服务多个来源，权限各自校验。
建议新执行后端采用 SQLAlchemy Core 2.x + 对应驱动，MySQL 首期使用 PyMySQL；SQLGlot 做 SQL 解析和范围检查，官方 Python MCP SDK 提供 stdio 工具。SQLAlchemy 管连接池、驱动绑定和事务，不引入 ORM 业务模型；后续 PostgreSQL 必须补驱动、方言及语义适配验证。
依据：本地 DBHub 1.2.0 的通用 execute_sql 只有 sql 参数，Custom Tools 需预注册且错误可能带参数；不利于任意动态查询和跨调用固定事务。SQLAlchemy 原生支持绑定参数与事务。实施时完成同范围回归后移除旧数据库 MCP/配置及无其他使用方的依赖，不保留两套查询后端；本轮仅变更设计。
成熟实现参考：[SQLAlchemy](https://github.com/sqlalchemy/sqlalchemy)、[SQLGlot](https://github.com/tobymao/sqlglot)、[DBHub](https://github.com/bytebase/dbhub)。SQL 解析能力不等于行级授权。

## 管理对象与字段

HTTP 业务字段沿用 camelCase；内部配置、MCP 工具及结果使用 snake_case。下表列出的对象为发布格式，必填字段均须类型校验、拒绝未知字段；可选项显式标注。

| 对象 / 归属 | 字段与类型 | 规则 |
| --- | --- | --- |
| ConnectionProfile / 受保护部署配置 | connection_key:string, revision:int, enabled:bool, driver:enum, host:string, port:int, database:string, username_ref:string, password_ref:string, tls:object, limits:object | driver 首期 mysql+pymysql；tls含verify_identity:bool=true、ca_ref?:string；密钥引用如env:REPORT_DB_PASSWORD，只允许管理员登记的env/Secret名；地址与账号信息不进入模型目录 |
| 连接 limits / 同上 | connect_timeout_s:int=10, query_timeout_s:int=30, pool_size:int=2, max_overflow:int=0, pool_recycle_s:int=1800 | 初始建议值，须压测；另设全实例/连接总并发上限，不能只限制每个 Run 的池 |
| DataSource / Python 业务资产 | source_key:string, version:int, name:string, description:string, domain:string, semantic_ref:string, dataset_refs:string[], query_catalog:string, coverage:object, enabled:bool | 只记录业务定义；coverage 包含 period_basis、available_periods、supports_as_of、freshness，动态信息须带核验时间；指标/字段只返回当前授权子集 |
| SourceBinding / 受保护部署配置 | binding_key:string, revision:int, environment:string, tenant_scope_ref:string, source_key:string, connection_key:string, schema_profile:string, security_scope_ref:string, enabled:bool | 授权上下文必须唯一匹配；tenant_scope_ref/security_scope_ref 对应 Java 登记范围，含真实值的配置不入 Git；0/多条均报错，不自动换库 |
| SchemaProfile / Python 业务资产 | profile_key:string, version:int, dialect:string, datasets:object, dictionaries:object, row_isolation:enum | datasets 登记模型可用表/视图名、物理映射、允许列、关联键和受审查的授权参数；隔离方式 query_spec_only/database_rls/scoped_readonly_views |
| SemanticModel / Python 共享资产 | domain:string, version:int, entities:object, joins:object[], periods:object, units:object, rule_refs:string[] | joins 必须有粒度、基数及去重规则；跨库关联只认已登记业务键；报告库 first/second 关系不能套问数库 parent 关系 |
| Metric / QuerySpec 目录内 metrics.json | metric_key:string, version:int, name:string, aliases:string[], kind:enum, query_id?:string, output_field?:string, grain:string, unit:string, period_modes:string[], rule_ref?:string | kind 为 direct/derived；direct 必填query_id/output_field，derived必填rule_ref且由规则声明输入查询/字段；业务表中的几千条指标记录由dataset查询返回，不逐条复制成静态Metric |
| QuerySpec / 现有 JSON+SQL | 保留 id/version/status/source_keys/dialect/grain/parameters/output/requires_queries/validation；增加 schema_profiles:string[], batch?:object, checks:object[] | batch 显式声明批量参数、结果键和可合并维度；checks 使用已实现的规则类型，不能把文字 validation 当可执行代码；只执行 defined 且当前来源已验证的版本 |

连接路径由 `CCSDK_DATA_CONFIG` 指定，相对值以仓库根为基准；文件内引用以配置文件父目录为基准。来源登记路径相对仓库根，QuerySpec的sql_file继续相对业务域目录，模板文件引用相对模板目录，禁止逃逸登记目录。Secret 值不写配置示例、Git、Prompt 或日志。
source_key 示例 qa_db/report_db 表示两个业务来源，hpm 是共享业务域；物理连接及 schema_profile 分别绑定，report_db 未连接时不能回退 qa_db。同名表不表示字段字典、历史覆盖或实值等价。

## 管理方式与发布

一期提供配置文件及管理命令，在python/目录执行拟议入口 `python -m data_access.manage`：validate 检查类型/引用/绑定唯一性；test-connection 检查连接和只读账号；verify-source 核对字段、隔离和 QuerySpec 基准；publish 原子启用已验证修订；disable 停用并使运行授权失效。命令只接受受信配置位置和逻辑key；CCSDK_DATA_CONFIG的相对值仍以仓库根为基准，不从业务工具执行。
Java 管理页面按连接、业务数据源、语义/指标、模板使用情况四个视图组织：连接页提供测试/启停/密钥更新；来源页展示覆盖、schema、绑定与 ACL；指标页显示口径/版本/验证；模板页显示绑定覆盖、缺口及受影响版本。普通业务用户只看到 Java 筛选后的可用能力和模板。
部署配置和业务资产分别保持一个权威来源：连接/绑定由受保护配置维护，语义/QuerySpec/模板由 Python 仓库维护；Java 管理页调用受控发布流程或提交资产变更，不额外维护可独立编辑的第二份语义。页面不是一期取数的前置依赖。
发布状态 draft -> validated -> published -> disabled；运行固定 asset_revision 和 binding_revision，更新供新 Run 使用。停用/撤销禁止下一次查询，在途任务最长15秒内检测并取消，交付结果前再检查；普通修订不改正在运行的计划。轮换连接密钥后废弃旧连接池并重新授权，不能继续用旧凭据。
可变更对象都记录 revision、changed_by、changed_at、reason；有引用的对象只能停用，发布前列出受影响模板/指标。回滚只选择仍兼容且通过当前权限校验的旧版本，不能恢复已撤销权限。

## Java 授权与传值

浏览器 -> Java -> Python 沿用现有 Run 请求：payload 仅 templateKey；input.text 提供期间与要求，附件走 attachmentRefs。tenant/sub 只取已验证 Run JWT；不在 payload 增加数据库、SQL、连接、项目授权清单或 Token。
Java 在签发 Run 前登记该 Run 的数据授权；拟新增 Java 内部回调 `POST /internal/v1/data-grants/resolve`，请求含 runId、capabilityRef、tenant、subject、sourceKeys。Python 从已验证身份和受控资产组装请求；Java 必须核对自己的 Run 记录及当前 ACL，不能按提交身份直接授权。
回调响应为 `grant_ref:string, revision:int, expires_at:timestamp, template_keys:string[], source_scopes:object[]`；每个 source_scope 含 source_key、scope_ref、project_ids、policy_ref、allowed_query_ids、allow_dynamic_sql。project_ids 为该数据源真实授权键，仅内部持有；空集合表示无权限，不表示全量。实体候选工具将业务对象映射为不透明引用。
回调地址取服务端 `CCSDK_DATA_AUTH_URL`，采用服务身份认证与 TLS；该服务凭据不同于业务 Token、Run JWT 和模型密钥。Grant 接口是拟新增 Java 契约，当前 Runtime 不能仅凭已有 JWT 推导项目权限，也不把该回调伪装成现有业务 Token MCP。
每次数据库/结果读取及交付前复核grant和当前配置启停状态，长查询期间至少每15秒复核，到期不得继续；撤销/校验不可用时停止并丢弃未交付结果。Grant不进入模型或普通日志；审计仅留引用、修订和脱敏关联。业务Token继续仅向REQ-001明确登记的业务MCP注入，data MCP不接收它。

## 模型数据库工具

共同约束：所有调用绑定服务端 RunContext；模型不能传 run_id、tenant_id、connection_key、DSN 或授权参数。scope_ref 是已授权业务范围引用，只能缩小范围；未指定范围仅在当前上下文唯一时自动绑定，否则返回需消歧。工具只暴露固定集合，不为每个库/指标增加模型工具。

| 工具 | 模型入参 | 返回 / 处理 |
| --- | --- | --- |
| list_data_sources | query?:string, cursor?:string, limit?:int<=50 | source_key/name/description/coverage/connection_status；授权过滤后的分页目录 |
| describe_data_source | source_key:string, topics?:string[], dataset_refs?:string[] | 指定数据集 schema、语义、方言、可用查询及 dynamic_sql_enabled；只读探测的连接状态不含地址 |
| resolve_entities | source_key:string, entity_type:string, query:string, parent_ref?:string, cursor?:string | 项目/任务/指标候选entity_ref、业务名、路径、期间；项目/项目集合另返回scope_ref，服务端映射真实键；多候选不默认第一条 |
| find_query_specs | source_key:string, intent?:string, metric_key?:string, scope_ref?:string, cursor?:string | intent/metric_key至少一个；返回query_id/version/status、口径、模型可填参数、输出和阻塞原因 |
| execute_query_spec | source_key:string, query_id:string, parameters:object, scope_ref?:string, entity_refs?:object | 运行固定查询及强制依赖诊断；版本取固定目录；parameters只接受origin=user_intent；entity_refs把声明为authorized_resolution的参数名映射到不透明实体引用，tenant/context仍自动注入 |
| execute_readonly_sql | source_key:string, sql:string, parameters:object, scope_ref?:string, purpose:string | 执行模型生成的单条只读查询，返回同一结果契约；方言取来源，值使用 :name 绑定；执行来源标记 dynamic |
| read_query_result | result_ref:string, cursor?:string, columns?:string[], page_size?:int<=200 | 从已经执行的结果读取授权页，不重新运行 SQL；服务端签发的游标绑定结果/范围；内部主键列不可请求 |

示例：`execute_query_spec({"source_key":"report_db","query_id":"fund_totals","parameters":{"year":"2025"},"scope_ref":"scope_selected"})`；scope_selected 是 resolve_entities/当前可信上下文产生的引用，tenant_id/project_id 自动解析。此例只演示参数形状，报告源验证完成前仍拒绝执行。
动态例：`execute_readonly_sql({"source_key":"report_db","scope_ref":"scope_selected","sql":"SELECT name, progress FROM task_view WHERE progress < :threshold","parameters":{"threshold":50},"purpose":"查找进度不足50%的任务"})`；task_view/name/progress 为示意名称，实际只能用 describe 返回的已授权视图及列。

## 执行与动态 SQL 边界

两条路径共用：复核授权 -> 解析绑定/方言 -> 校验查询与参数 -> 建立只读连接/事务 -> 驱动绑定执行 -> 完整性和业务校验 -> 保存结果及证据。标识符由登记映射选择，不能把参数拼成表/库名。SQLAlchemy 绑定处理重复参数、NULL、日期、Decimal；列表需声明 expanding，空列表表示空结果，不能变成不加过滤。
固定查询优先；未命中但语义明确时模型可写 SQL。动态结果可用于问数和补充分析；固定槽位只有登记允许动态查询、定义/期间/输出已明确且通过同等校验时才能使用动态结果，不允许覆盖已有固定绑定或绕过 needs_definition/blocked。
SQLGlot 按已验证方言只允许单条 SELECT 或只读 WITH，检查所有子查询/CTE/UNION/关联的表、列和函数；拒绝多语句、DDL/DML、写入型CTE、锁、文件/网络/UDF、系统表和外部库。未知语法拒绝，不能仅检查 SELECT 前缀；模型不能改变查询超时、最大行数或开启危险函数。
动态 SQL 必须具备数据库侧的有效行隔离：PostgreSQL 可用不可绕过的 RLS 角色；MySQL 首期要求只读账号仅有按授权范围过滤视图的 SELECT 权限，且无底表/越范围视图权限。当次scope_ref对应的获准范围必须覆盖该账号全部可见行，任意SQL才不会越行；多项目权限无法匹配时只开放固定QuerySpec。视图按真实授权范围管理，不把可由SQL更改的会话变量当授权。
固定 QuerySpec 可在 query_spec_only 模式运行，但需逐资产审查每个表的租户/项目过滤与关联，禁止模型覆盖授权参数；不自动重写任意 SQL 来声称实现行级权限。MySQL 动态查询的视图/账号部署成本是明确代价，未配置隔离的来源保持 dynamic_sql_enabled=false，不能假装已经支持。
data MCP独立于SDK模型进程；Runtime在模型启动前用Java回调验模板权限，再以私有启动上下文传已验证身份和固定资产版本，data启动及每次执行重新核验Grant。数据库密钥只给data进程，不转发原始Run JWT。数据库/报告工具注册在同一data MCP进程，共用执行器/结果仓库；prepare_report_data启动进程内受控后台任务，状态由get_report_data读取。
正式多租户运行必须隔离密钥文件、进程权限及直连数据库网络，去掉可旁路取数的原始DB工具；当前bypassPermissions与同账号进程不能证明隔离已成立。拟采用每Run独立data MCP；Client跨轮继续会话时重建MCP并重新授权，新Run重新取数，历史报告走授权文件引用，不能直接复用旧工具上下文。
连接池按连接修订、凭据版本、租户/授权范围及会话设置隔离；事务结束回滚并清理上下文，取消时终止数据库语句，无法确认取消的连接直接废弃。禁止将池简单按 source_key 缓存，也不因 Client 跨轮复用继续使用旧 RunContext。
查询必须设置数据库端超时：MySQL使用适用SELECT的MAX_EXECUTION_TIME，PostgreSQL使用事务内statement_timeout，并验证实际方言行为；Python等待超时不能当作SQL已终止。取消适配需终止本次数据库语句并核验，失败连接不复用；Runtime按连接发放并发名额，覆盖所有Run的独立MCP进程。

## 结果契约与存储

统一返回 `status:ok|partial|blocked|error, result_ref, source_key, query:{kind,id,version}, columns:[{name,type,unit,nullable}], row_count, preview, period, scope_ref, snapshot_ref, complete, warnings, evidence_refs`。preview默认最多20行；row_count是已物化行数，complete仅指请求结果完整，字段缺失另由checks/warnings表示。动态SQL无法核验期间/粒度时标unknown，不因当前报告参数存在就宣称已按其过滤，也不得挂接要求该口径的槽位。
结果保存在隔离的 Run 目录，数据库明细不入 Prompt 全量上下文、公共 SSE、普通日志或 Git；模型按引用分页读取。数值 Decimal 以十进制字符串+列类型返回，日期用ISO格式并登记时区；NULL、无记录、未填报、0分开。分页游标不是SQL offset，过期结果返回 RESULT_EXPIRED。
evidence_ref 关联实际来源、查询/规则版本、绑定修订、业务期间、采集时间和结果行引用；内部主键只用于关联，模型接收不透明 row_ref。QuerySpec原文可随部署版本追溯；动态SQL及绑定值只放受限执行记录，公共审计仅留脱敏摘要/指纹，数据库异常不回显SQL实值/凭据。
超量以 byte/row 限额停止并标 complete=false，不对截断记录计算全量汇总或填完整表。Run默认建议结果总量50MiB、单结果10万行，管理员配置；持久化保留期由部署决定并与Run归档一致，引用过期不会触发隐式重新查询。
稳定错误码：SOURCE_UNBOUND、SOURCE_AMBIGUOUS、SOURCE_NOT_VERIFIED、SCOPE_DENIED、GRANT_EXPIRED、PARAMETER_INVALID、QUERY_BLOCKED、SQL_REJECTED、QUERY_TIMEOUT、RESULT_INCOMPLETE；只返回业务可理解原因。可重试与完整性由服务端判断，模型不能无界重试。

## 工程要求检查

| 要求 | 状态 | 依据 | 差距与后续处理 |
| --- | --- | --- | --- |
| REQ-001 | 部分满足 | Java授权回调使用独立服务身份；业务Token继续按MCP逐请求注入，不进入data工具 | 新工具进程隔离、在途撤销、轮换、日志脱敏及Java链路均待实现验收 |
| REQ-002 | 部分满足 | payload仅templateKey；可信配置绑定来源、执行资产与权限，问数/撰写共享工具 | 模板校验、Grant接口、数据库侧行隔离、版本审计未实现；未开放来源不执行动态SQL |
