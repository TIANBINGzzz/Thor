# 校本数据库管理与查询工具改造

2026-09-14用户确认：当前唯一数据库为校本数据库；本期单租户，保留以后扩展多租户的边界。本文为待实施设计，当前Runtime/SQL/目录尚未改造；决策见[ADR-022](../ADR/022-school-database-single-tenant.md)，模板流程见[批量计划](template-batch-data-plan.md)。

## 当前事实与改造目标

当前连接由python/runtime/config.py的create_database_mcp_server按database-qa/workflow.json、workflow.env和dbhub.readonly.toml装配；语义在该Workflow内，32项共享QuerySpec在.claude/query-specs/hpm/，writing-docx尚未接入模板取数。
旧sources.json中的qa_db/report_db是尚未整理的历史逻辑标识，不证明存在两个物理数据库。统一目标source_key=school、名称=校本数据库；问数与撰写使用同一个来源。HPM是已整理业务域，后续同库其他业务域分别登记，不能据现有12表说明整个校本库。
来源身份统一不代表结构兼容已验证：旧报告模板的任务绩效关系、first/second标题字段、资金字典、历史版本与评分在校本库逐项核验；保留needs_definition/blocked及历史核验证据，不机械改名后全部启用。

## 数据资产归属

沿用QuerySpec业务域根目录，在.claude/query-specs/hpm/school/集中放校本库HPM语义、指标与查询；.claude/data-sources/school.json只做该数据库总索引。每个库仅一份来源登记，一个库可引用多个域包；不同库在同域下使用不同source_key子目录。
school.json中profiles.hpm指向上述包；包内semantics/维护字段、关联、期间与口径，metrics.json维护指标定义，specs/和sql/沿用QuerySpec。重复实例指标仍从业务表批量返回，不生成几千份静态SQL。共同口径确认相同后显式引用，不自动把其他库同名字段视为等价。
连接信息移出database-qa工作流，由CCSDK_DATA_CONFIG指定受保护JSON；相对值以仓库根为基准，配置内部文件引用以配置父目录为基准。密钥只用env/Secret引用，不能存进资产、Prompt或Git；域包内sql_file相对包根，其他资产引用相对仓库根。

## 最小字段

HTTP继续camelCase，内部资产与MCP使用snake_case；下列新增字段为拟议契约，未列为可选的字段必填。只实现一份静态配置及解析函数，不建设绑定规则引擎或配置中心。

| 对象 | 字段 / 类型 | 作用 |
| --- | --- | --- |
| Source / school.json | source_key:string, name:string, profiles:object, connection_ref:string, policy_ref:string, version:int, enabled:bool | school指向一个连接配置和一个访问策略；profiles按业务域登记目录，不含真实地址或租户值 |
| Connection / 受保护配置 | connection_ref:string, driver:string, host:string, port:int, database:string, username_ref:string, password_ref:string, tls:object, revision:int, limits:object | 首期mysql+pymysql；TLS校验身份；limits登记连接/查询超时、池大小及全实例并发限制；换地址不改模板 |
| SingleTenantPolicy / 受保护配置 | policy_ref:string, mode:string=single_tenant, tenant_id_ref:string, data_tenant_id_ref:string, source_keys:string[], capability_refs:string[], template_keys:string[], datasets:object, project_scope:object, revision:int | tenant_id_ref校验JWT租户，data_tenant_id_ref解析业务表租户键；两者可引用同一配置但不默认相等；datasets明确表/列/函数白名单 |
| project_scope / 策略内部 | mode:all_school/selected_projects, project_ids?:string[] | all_school仅在管理员确认当前使用者可读该登记学校范围时启用；selected_projects必填非空集合，空集合拒绝；不预设所有用户有全库权限 |
| DataContext / 每Run内部 | run_id:string, tenant_id:string, user_id:string, capability_ref:string, policy_revision:int | tenant/user来自已验Run JWT；服务端传Worker，再由工具传执行器；模型不能覆盖，不放进业务payload |
| ResolvedAccess / 解析结果 | source_key, connection_ref, connection_revision, data_tenant_id, project_scope, allowed_datasets, allowed_queries, dynamic_sql_enabled, access_fingerprint | 固定和动态查询共用；解析失败即拒绝；租户、来源、账号/权限版本进入指纹 |
| QuerySpec / 域包 | 保留id/version/status/parameters/output/requires_queries；source_keys统一school，增加checks与batch声明 | checks仅允许已实现验证器；batch明确数组参数、结果键和合并维度；名称变更不抹掉旧验证范围 |
| Metric / metrics.json | metric_key, name, aliases, kind, grain, unit, period_modes, query_ref或rule_ref | direct引用query_id+输出字段；derived引用规则及其依赖；全局定位用source_key+domain+metric_key |

索引示意：`{"source_key":"school","name":"校本数据库","profiles":{"hpm":".claude/query-specs/hpm/school"},"connection_ref":"school_primary","policy_ref":"school_readonly","version":1,"enabled":true}`。school_primary是配置键，不是物理数据库名；示例不代表已完成登记。

## 单租户执行与扩展边界

保留现有Run JWT身份与Java的Capability/文件授权。Python拒绝不匹配所配置租户的请求，通过resolve_data_access(context, source_key)验证静态策略、来源/模板/能力和查询范围；本期不引入Java Data Grant回调或逐次远程权限请求。静态策略需由业务授权方确认，已有部门/项目差异不能静默扩大。
单租户是部署策略，不能删tenant参数、合并用户会话或用默认租户兜底。固定QuerySpec仍使用可信data_tenant_id及项目范围；实际SQL有tenant_id_字段就保留过滤。同一物理库是否还含其他租户行属于数据核验事项，不由“当前只有一个数据库”推出。
连接选择单独放resolve_connection(context, source_key)；本期读取source.connection_ref，未来可按(context.tenant_id, source_key)查连接映射。execute_query_spec/execute_readonly_sql及模板只依赖ResolvedAccess，不直接读环境变量或拼库名。
结果/证据记录从第一天带tenant_id、user_id、run_id、source_key、access_fingerprint；读取同时核验归属，实际工作目录仍沿RunStore受控根解析，不靠文件名保权限。默认不跨Run缓存；未来缓存必须包含租户/权限指纹、参数和版本，不能只用query_id。
连接池按租户、来源、连接/凭据修订及有效范围分组，结束回滚清理，轮换废弃旧池；不使用进程全局current_tenant或临时修改os.environ。应用只部署一个租户时这些仍是普通参数和字典键，不引入多租户调度平台。

## 数据库与报告工具

统一data MCP供问数/撰写使用，工具保持固定集合。模型使用source_key=school，省略时仅当当前能力恰好授权一个来源才自动绑定；不暴露DSN/密码，也不要求显式connect。HTTP模板payload仍只传templateKey，报告年份/要求放input.text。

| 工具 | 主要入参 | 返回 / 约束 |
| --- | --- | --- |
| list_data_sources | query?, cursor? | 本期只返回school的名称/范围/状态，后续可多来源；授权过滤 |
| describe_data_source | source_key, domain?, topics?, datasets? | 按需返回该库域的字段、口径、可用指标、查询及动态SQL状态；不全量注入Prompt |
| resolve_entities | source_key, domain, entity_type, query, parent_ref?, cursor? | 校本库项目/任务/指标的业务名称及不透明entity_ref/scope_ref；同名必须消歧 |
| find_query_specs | source_key, domain, intent?, metric_key?, cursor? | intent/metric_key至少一项；返回query_id、定义/参数/输出/状态，版本由服务端固定 |
| execute_query_spec | source_key, domain, query_id, parameters, scope_ref?, entity_refs? | 固定SQL和依赖检查；模型只填业务参数，租户和授权键由Context/引用解析注入 |
| execute_readonly_sql | source_key, domain, sql, parameters, purpose, scope_ref? | 模型生成SQL，值用:name绑定，表列必须来自describe；结果标dynamic，不自动改写指标库 |
| read_query_result | result_ref, cursor?, columns?, page_size? | 读取物化结果授权页，不重复执行SQL；返回结构和来源/期间/完整性/证据 |
| prepare/get/render_report | 同[模板计划](template-batch-data-plan.md) | 批量取数、章节事实读取和确定性填表复用相同执行器；模板角色hpm绑定school |

调用示例：`{"source_key":"school","domain":"hpm","query_id":"fund_totals","parameters":{"year":"2025"},"scope_ref":"scope_selected"}`。scope_selected由当前Run定位，不接受真实tenant_id；内部QueryRef统一(source_key,domain,query_id)，避免同库不同域查询重名。

## 执行实现与只读范围

沿用ADR-021的SQLAlchemy Core 2.x+PyMySQL执行建议，SQLGlot用于AST解析；参数绑定、连接池和事务交给成熟库。本地DBHub 1.2.0通用execute_sql仅接SQL，自定义参数工具需预注册；新执行器完成问数回归后直接替换旧DBHub装配和无其他使用方的依赖，不长期并行两套后端。
本期沿用python/tools/docx.py的SDK进程内MCP注册模式，data工具调用通用executor；一次性与持久Worker均在每个Run前接收不可变DataContext，工具调用时捕获本轮上下文，完成/取消先清理后台任务再清除上下文。Actor仍串行；凭据/权限指纹变化重建工具配置，不能把第一轮上下文永久闭包绑定。此模式不宣称构成生产沙箱。
固定查询：解析授权 -> 来源/版本/字段检查 -> requires_queries诊断 -> SQLAlchemy驱动绑定 -> 只读事务 -> 输出/完整性校验。nullable参数缺失与显式null分开；数组参数需声明expanding，空列表不扩大范围；多项目金额等只能按QuerySpec登记可加性汇总。
动态查询：只允许单条SELECT或只读WITH，检查所有子查询/CTE/UNION的表列函数；拒绝写操作、多语句、锁、系统表、文件/网络函数和未知语法。SQL解析不代表业务口径已验证，动态结果的期间/粒度无法证明时返回unknown。
当只读账号可访问的数据完全位于当前学校已授权范围时，单租户无需额外按用户建视图即可开放动态SQL；仍只开放登记表列。若账号还可读其他租户或用户未获准项目，须数据库侧缩小权限/视图后开放，或仅执行审查过的固定SQL；不凭模型补WHERE来声称完成隔离。
模型可用动态SQL补充分析；填固定模板仅允许已登记dynamic_policy且通过语义/期间/输出校验的槽位。不得因来源统一就绕过评分、成果去重和历史快照缺口，不自动以“最新反馈”填历史年度。
数据库端超时与应用超时分别实现；取消需终止SQL并核验，不确定的连接废弃。校本库一组查询使用同一只读一致性事务，物化完释放连接；撰写不占事务。建议初始连接超时10秒、查询30秒、池2个、全实例并发受限，取数计划/结果上限配置化且经压测调整。
模型/普通日志不接收连接凭据和业务Token；data不注入业务Token，business MCP继续REQ-001逐请求注入。当前bypassPermissions仍允许宿主资源访问，多租户生产前必须完成工具白名单及文件/进程/网络隔离，不把本期单租户便利当多租户验收。

## 管理与结果

一期仅提供校本库登记配置、validate/test-connection/verify-source命令、启停及版本回滚；校验包含真实表/列/字典与独立取数基准。未来管理页复用该模型，首期不建数据库管理平台、配置中心、发布队列或通用授权服务。配置由Python部署维护，Java校验用户/能力/文件权限，权限变更立即阻断下一次执行及结果交付。
结果统一为status、result_ref、source_key、domain、query_id/version、columns、row_count、preview、period、scope_ref、snapshot_ref、complete、warnings、evidence_refs。preview最多20行，分页上限200行；row_count仅为物化结果数，complete不代表业务字段齐全；超量/截断不能填完整报表。
Decimal用十进制字符串+列类型，NULL/无记录/0分开；原始行、动态SQL与参数仅放受限Run结果目录，结果引用不可跨用户/租户访问。内部ID转不透明引用，对外保留业务名和证据；保留期与Run归档一致，不入Git。

## 基于现有代码的实施顺序

1. 资产集中：增加school.json；把hpm/specs、sql、coverage及测试移入hpm/school/，将database-qa的公共semantics移入该包；来源引用统一school并更新路径基准、catalog、模板query-bindings及来源说明。32项逐项分类核验，未验证不能升级状态；完成后删除旧sources.json与旧语义副本，不保留qa_db/report_db别名层。
2. 身份与配置：server.py的_internal_worker_payload增加由claims生成的内部DataContext；runtime/config.py由受控来源装配data工具，替换_workflow_database/create_database_mcp_server；agent_worker/session_actor按每轮上下文与配置指纹绑定/清理。runtime/protocol.py现有业务请求不新增tenant/connection字段。
3. 查询执行：新增python/data_access/{context,catalog,access,connections,executor,sql_policy,results}.py及python/tools/data.py；先接一条问数与一条动态SQL，再跑完已有18问。data_access只放通用代码，学校表名、字典和业务公式留资产中；修改mcp_auth规则只登记data无需业务Token。
4. 模板计划：新增python/reporting/{bindings,planner,rendering}.py和报告工具；在既有writing-docx解析templateKey、注册数据工具，新增template.json/slots，复用QuerySpec批量执行。先验证绩效表、资金、评分和证据正文，再覆盖40表，不复制Workflow。
5. 部署与验收：同步requirements/package依赖、deploy/compose.database.yaml和write-env相关路径；连接配置不再挂在database-qa目录。同步README/ARCHITECTURE、schema/引用测试和18问/40表基准，目录搬动后更新测试BASE/ROOT，特别移除旧测试对report_db未绑定的过期断言。

## 以后扩展多租户

优先支持一租户一库：access.py由静态策略扩为Java授权或受控租户表，connections.py按tenant_id+source_key选连接；资产包按相同schema复用，模板和模型工具参数保持不变，新增租户不复制整个Workflow。连接路由不代替用户/项目授权，各租户策略分别检查。
共库按tenant_id隔离需另做数据库侧行级防护、只读账号/视图及动态SQL绕过回归；不能只改一个开关或追加WHERE。并发额度、连接轮换、结果与Client隔离都需两租户同业务ID测试。保留上述边界降低重构范围，不承诺多租户无需实施和验收。

## 工程要求检查

| 要求 | 状态 | 依据 | 差距与后续处理 |
| --- | --- | --- | --- |
| REQ-001 | 部分满足 | 业务Token继续按MCP注入，data不接收；DataContext只含可信身份 | 凭据轮换、每Run上下文、隔离与真实Java链路待实现验收 |
| REQ-002 | 部分满足 | templateKey/Capability契约不变；单租户静态来源授权，执行资产服务端解析 | 模板及范围校验未实现；静态策略不覆盖真实细粒度ACL时须接Java授权，不能默认全库可读 |
