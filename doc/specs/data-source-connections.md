# 数据库管理与查询工具

唯一来源为校双高数据库，标识为 `schoolDoubleHigh`，业务域为 `hpm`。已实现按库组织资产、SQLAlchemy执行器和SDK MCP装配；多来源使用同一套工具，当前共享租户范围见下文。撰写见[通用文档工具](../ADR/029-native-office-document-tools.md)，输入见[能力 payload](capability-payload.md)。

## 目录与职责

```text
.claude/databases/schoolDoubleHigh/
  source.json               来源、能力绑定和域知识登记
  schema/hpm.json           13表158列的真实类型、说明、函数及内部列
  metrics/hpm/*.yaml         项目/任务/绩效/资金四个主题，27项契约及内嵌SQL
                            共享参数类型及6项pending原因随主题保存
  semantics/business.md     业务默认口径、期间、单位及事实来源
  semantics/relationships.md 关联、归属和去重
python/data_access/         通用连接、授权、查询和结果
python/runtime/data_services.py  每Run装配及私有配置快照
python/workflows/writing_docx/   可信模板上下文和参考副本
python/tests/databases/      按数据库验证结构、指标SQL及覆盖
config/databases.json        部署配置；本版进入私有Git和镜像，集中保存各来源连接/策略
config/certificates/         部署侧CA证书，路径相对databases.json
```

新增数据库只增加自己的source.json、知识及私有连接配置。source.capabilities声明能使用该来源的能力；Workflow只声明data_access=required或optional；普通撰写按已配置来源启用数据工具，固定模板要求全部绑定来源可用。私有policy进一步校验身份与范围，登记不等于授权。不复制工具或Workflow。

## 字段与配置

source.json不登记连接路径。databases.json结构为`{version:1,sources:{source_key:{connection,policy}}}`，内部不重复source_key。`CCSDK_DATABASES_FILE`指定该文件，相对路径以项目根目录为基准，默认config/databases.json。本版直接读取镜像内/app/config/databases.json，构建仅做离线结构检查，修改须重新构建部署；仍可显式挂载目录覆盖，见[ADR-028](../ADR/028-bundled-database-config.md)。
数据库执行器按来源键读取用户名和密码；只有配置路径传给Worker，SDK环境不接收该变量。CA路径相对databases.json解析，不允许模型传连接参数。普通会话不加载数据库；普通撰写允许配置文件缺失，格式损坏则失败；问数和固定模板缺来源连接必须失败。每Run读取独立快照，配置内容变化触发Client重建。

| 对象 | 字段 | 约束 |
| --- | --- | --- |
| Source | source_key, name, version, enabled, capabilities, domains | source_key为业务标识，不是物理库名；能力绑定在此维护 |
| Source.domains.hpm | metrics, schema, documents, entities | 只登记必要知识；schema由工具组织成字段说明，关联和口径按需提供 |
| Connection | tenant_id, driver, host, port, database, username, password, tls, revision, timeout_seconds, max_rows | 由sources键确定来源，校验当前身份；mysql+pymysql，sqlite仅用于测试；凭据不进入模型资产 |
| Policy | tenant_id, business_tenant_id, revision, users, capabilities, templates, project_scope, domains, dynamic_sql_enabled | 与connection同属一个来源键；JWT租户与业务租户独立，来源/能力/模板取交集 |
| Policy.domains.hpm | queries, tables | 允许的查询和表名列表；表列类型、函数及内部列由schema单独维护，不重复复制 |
| project_scope | mode=selected/all_school, project_ids | selected必须有非空项目集合；全校只由可信管理员授权 |
| QuerySpec | id, name, description, aliases, version, grain, parameters, output, semantics, sql, requires_queries?, checks? | 主题 YAML 中的 id 为 query_id，SQL 内嵌；未定义原因在 pending 中登记 |
| DataContext | run_id, tenant_id, user_id, capability_ref, run_directory, template_key? | 身份来自已验JWT，模型参数不能覆盖 |

TLS默认要求CA及身份校验；私有配置可显式tls.mode=disabled适配既有连接，不会自动降级。本次实库沿用既有连接，不算生产TLS验收。

2026-09-20按用户要求，校双高暂时向所有已通过Runtime鉴权的租户和用户开放：该来源的policy与connection均显式设置`tenant_id: "*"`，policy.users设为`all_authenticated`。具体租户值仍按身份精确匹配；business_tenant_id继续限定原业务数据范围，Capability、模板、查询白名单及Run结果归属仍校验。恢复租户限制时收紧这三处配置并重新部署。

## 工具传值

统一`mcp__data__<name>`，内部参数snake_case，HTTP仍camelCase；schoolDoubleHigh保持大小写。工具拒绝未知顶层字段，失败返回isError及安全错误码。

| 工具 | 入参 | 返回及约束 |
| --- | --- | --- |
| list_data_sources | 无 | 本Run获准来源的标识、名称、域及范围 |
| describe_data_source | source_key, domain, topics? | 表列/函数白名单、动态开关及所选语义文档 |
| resolve_entities | source_key, domain, entity_type, query, parent_ref?, parameters? | 名称、entity_ref和项目scope_ref；同名须消歧 |
| find_query_specs | source_key, domain, intent? / metric_key? | 至少一个条件；名称/别名及中文词对排序，metric_key直接匹配query_id.field公开输出；返回说明、参数、状态，最多50条 |
| execute_query_spec | source_key, domain, query_id, parameters, scope_ref, entity_refs? | 固定查询/依赖诊断；租户及项目键由可信上下文注入 |
| execute_readonly_sql | source_key, domain, sql, parameters, purpose, scope_ref | 模型写SELECT，值以:name绑定；结果标dynamic |
| read_query_result | result_ref, cursor? | 同Run物化结果每页100行，内部ID不返回，不重复执行SQL |

例如：`{"source_key":"schoolDoubleHigh","domain":"hpm","query_id":"fund_totals","parameters":{"year":"2025"},"scope_ref":"scope_..."}`。scope_ref由当前Run解析，不能复用上一轮或另一库的引用。
执行及分页返回provenance，包含来源、域、查询/资产版本、公开参数、采集时间及dynamic标记；不含真实身份、连接参数或策略内容。

## 执行与管理

调用链：server可信payload → agent_worker → RunServices.bind → Executor。每轮重绑身份、配置和已登记运行资产快照（不含测试/私有文件），关闭时取消活动查询并清除上下文；结果记录包、查询、连接、策略版本。原始结果保存在受限Run目录，不跨Run缓存。
固定SQL经SQLGlot全AST检查和SQLAlchemy绑定，在只读一致性事务中执行；字段顺序必须匹配输出声明。保留Decimal、NULL、无记录和零的区别；行数/字节超限不得将截断结果视为完整数据，写作不占数据库事务。
动态SQL还要求database_scope_enforced=true且scope_source_key匹配当前来源且scope_policy_revision匹配策略版本；数据库账号/视图必须限制于整个授权范围，不能靠模型补WHERE。拒绝跨库、写语句、锁、星号、系统对象、未知列/函数及内部键输出；动态结果不能直接覆盖固定模板。Agent依据所选模板指南自主规划取证和撰写，通用文档工具边界见[ADR-029](../ADR/029-native-office-document-tools.md)；数据库工具不承担文档重建或报告编排职责。
取消会关闭活动MySQL socket或中断SQLite；查询及网络操作有超时。Run内串行，NullPool无共享池；跨进程额度及账号最大连接数仍需部署约束，不宣称已有全实例限流或跨库一致事务。
管理员在python目录用`python -m data_access list/validate/probe`，参数见--help。启停及授权通过受保护配置和包发布，变更后重建服务；没有管理网页、热更新或自动改写指标库。
未来多租户主要替换access.py及connections.py的可信策略/连接查找，工具/模板仍传source_key/domain/query_id；共库行权限、文件/进程/网络隔离和双租户并发需独立实施。

## 验证与要求

真实来源核验见[来源记录](../verification/report-source-audit.md)，资产覆盖由 python/tests/databases 维护。历史快照、评分和成果口径仍有缺口，不能因工具成功或目录迁移宣称业务数据完备；文稿质量须独立验收。

| 要求 | 状态 | 依据与差距 |
| --- | --- | --- |
| REQ-001 | 部分满足 | data不接业务Token，business沿原规则注入，Run重绑有测试；真实Java撤销及日志全链路待验收 |
| REQ-002 | 部分满足 | 来源/能力/模板由可信配置装配；阶段性共享来源、Java授权及生产隔离差距保留 |
