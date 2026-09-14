# 数据库管理与查询工具

唯一来源为校双高数据库，标识为 `schoolDoubleHigh`，业务域为 `hpm`。已实现数据库优先的资产布局、SQLAlchemy执行器和SDK MCP装配；单租户起步，多来源使用同一套工具。模板见[批量计划](template-batch-data-plan.md)，产品流程见[对话与报告](conversation-reporting-product.md)。

## 目录与职责

```text
.claude/databases/schoolDoubleHigh/
  source.json              名称、域、连接/策略引用、版本和启停
  query-specs/hpm/
    catalog.json           查询索引、实体解析定义及语义主题
    semantics/             字段、两棵指标树、关联、期间及口径
      tables/              各表的模型可读字段说明
    metrics.json           指标检索键到查询输出字段的映射
    rules.json             尚未定义的派生规则及阻塞原因
    specs/                 参数、输出、状态、依赖检查和版本
    sql/                   固定参数化只读查询
    coverage.json          18问及各表的覆盖关系
    tests/                 合成口径测试及人工核验记录
python/data_access/        通用来源授权、连接、执行、结果与Run上下文
python/reporting/          模板解析、批量取数、绑定和DOCX渲染
python/tools/data.py       data MCP薄适配层
python/tools/reports.py    reports MCP薄适配层
deploy/                   受保护连接/权限配置示例及部署脚本
```

新增库时放独立 `databases/<新source_key>/source.json` 及域资产，配置自己的连接/策略，加入获准Workflow的data_sources。不复制工具和Workflow，不混用同名指标。

## 字段与配置

`CCSDK_DATA_CONFIG`指向受保护JSON，相对路径以仓库根为基准。connections、policies分别按connection_ref、policy_ref查找。秘密只使用`env:NAME`或`file:relative-file`，文件相对配置父目录；不进入Git、Prompt和日志。
父Runtime只向Worker传递当前Workflow已登记且身份获准来源的env秘密；SDK子进程使用独立白名单，不继承数据库秘密。秘密或配置变更后重建服务。

| 对象 | 实际字段 | 约束 |
| --- | --- | --- |
| Source | source_key, name, profiles, connection_ref, policy_ref, version, enabled | profiles.hpm=query-specs/hpm；来源标识不是物理库名 |
| Connection | source_key, tenant_id, driver, host, port, database, username_ref, password_ref, tls, revision, timeout_seconds, max_rows | mysql+pymysql；sqlite用于合成验证；每个快照独立连接并回滚释放 |
| Policy | source_key, tenant_id, business_tenant_id, revision, users, capabilities, templates, project_scope, domains, dynamic_sql_enabled | JWT租户和业务表租户分别检查；users为列表或显式all_authenticated |
| project_scope | mode=selected/all_school, project_ids | selected必须有非空项目集合；全校仅由可信管理员配置 |
| domains.hpm | queries, tables, functions, internal_columns | 固定查询、表列/函数白名单及不对外输出的列 |
| DataContext | run_id, tenant_id, user_id, capability_ref, run_directory, template_key? | 身份来自已验JWT，不接受业务payload覆盖 |
| QuerySpec | id, version, status, parameters, output, sql_file, requires_queries?, checks?, batch | 非defined不执行；目前按标量参数展开批次 |

TLS默认要求CA及身份校验。受保护配置可显式声明`tls.mode=disabled`适配既有连接，TLS失败不会自动降级。本次实库模拟沿用旧连接的明文传输，不算生产TLS验收；部署示例保留身份校验。

## 工具传值

统一`mcp__data__<name>`，内部参数snake_case，HTTP仍camelCase；schoolDoubleHigh保持大小写。工具拒绝未知顶层字段，失败返回isError及安全错误码。

| 工具 | 入参 | 返回及约束 |
| --- | --- | --- |
| list_data_sources | 无 | 本Run获准来源的标识、名称、域及范围 |
| describe_data_source | source_key, domain, topics? | 表列/函数白名单、动态开关及所选语义文档 |
| resolve_entities | source_key, domain, entity_type, query, parent_ref?, parameters? | 名称、entity_ref和项目scope_ref；同名须消歧 |
| find_query_specs | source_key, domain, intent? / metric_key? | 至少一个检索条件；说明、参数、公开输出和状态，最多50条 |
| execute_query_spec | source_key, domain, query_id, parameters, scope_ref, entity_refs? | 固定查询/依赖诊断；租户及项目键由可信上下文注入 |
| execute_readonly_sql | source_key, domain, sql, parameters, purpose, scope_ref | 模型写SELECT，值以:name绑定；结果标dynamic |
| read_query_result | result_ref, cursor? | 同Run物化结果每页100行，内部ID不返回，不重复执行SQL |

例如：`{"source_key":"schoolDoubleHigh","domain":"hpm","query_id":"fund_totals","parameters":{"year":"2025"},"scope_ref":"scope_..."}`。scope_ref由当前Run解析，不能复用上一轮或另一库的引用。
执行及分页返回provenance，包含来源、域、查询/资产版本、公开参数、采集时间及dynamic标记；不含真实身份、连接参数或策略内容。

## 执行与管理

调用链：server可信payload → agent_worker → RunServices.bind → Executor。每轮重绑身份、配置和资产快照，关闭时先取消计划/查询再清除上下文；结果记录包、查询、连接、策略版本。原始结果保存在受限Run目录，不跨Run缓存。
固定SQL经SQLGlot全AST检查和SQLAlchemy绑定，在只读一致性事务中执行；字段顺序必须匹配输出声明。保留Decimal、NULL、无记录和零的区别；行数/字节超限不得填完整报告。一个来源的计划同快照取数，写作不占事务。
动态SQL还要求database_scope_enforced=true且scope_policy_ref/revision匹配；数据库账号/视图必须限制于整个授权范围，不能靠模型补WHERE。拒绝跨库、写语句、锁、星号、系统对象、未知列/函数及内部键输出；动态结果不能直接覆盖固定模板。
取消会关闭活动MySQL socket或中断SQLite；query/socket/计划均有超时。Run内串行，NullPool无共享池；跨进程额度及账号最大连接数仍需部署约束，不宣称已有全实例限流或跨库一致事务。
管理员在python目录用`python -m data_access list/validate/probe`，参数见--help。启停及授权通过受保护配置和包发布，变更后重建服务；没有管理网页、热更新或自动改写指标库。
未来多租户主要替换access.py及connections.py的可信策略/连接查找，工具/模板仍传source_key/domain/query_id；共库行权限、文件/进程/网络隔离和双租户并发需独立实施。

## 验证与要求

原23条defined查询SQL和输出契约搬迁保持一致；原报告5组SQL已实库对照。补充一级建设指标、全周期预算及任务绩效关系；历史快照、评分和成果规则仍不得猜测。详见[来源核验](../verification/report-source-audit.md)。

| 要求 | 状态 | 依据与差距 |
| --- | --- | --- |
| REQ-001 | 部分满足 | data/reports不接业务Token，business沿原规则注入，Run重绑有测试；真实Java撤销及日志全链路待验收 |
| REQ-002 | 部分满足 | 来源/能力/模板受控；固定报告只挂数据和报告工具；外部Java旧协议及前端选择器仍须对齐 |
