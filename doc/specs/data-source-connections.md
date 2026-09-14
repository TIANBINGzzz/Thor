# 按数据库组织的数据源管理与查询工具

2026-09-14用户最新确认唯一数据库为校双高数据库，内部标识定为schoolDoubleHigh。按库集中管理，首期支持单租户、多数据源，保留多租户扩展边界；本文为待实施设计，Runtime/SQL/目录尚未改造。目录见[ADR-023](../ADR/023-database-scoped-asset-packages.md)，租户边界见[ADR-022](../ADR/022-school-database-single-tenant.md)，模板见[批量计划](template-batch-data-plan.md)。

## 当前事实与改造目标

当前连接由python/runtime/config.py的create_database_mcp_server按database-qa/workflow.json、workflow.env和dbhub.readonly.toml装配；语义在该Workflow内，32项共享QuerySpec在.claude/query-specs/hpm/，writing-docx尚未接入模板取数。
旧sources.json的qa_db/report_db及此前拟议school均待统一为source_key=schoolDoubleHigh、名称=校双高数据库；不代表多个物理库。hpm保留为已整理的项目/任务/资金/绩效业务域，不把库名当筛选条件，现有国/校双高口径须按查询定义核验，命名不修改SQL或物理库名。
来源身份统一不代表结构兼容已验证：旧报告模板的任务绩效关系、first/second标题字段、资金字典、历史版本与评分在校双高库逐项核验；保留needs_definition/blocked及历史核验证据，不机械改名后全部启用。

## 数据资产归属

每库一个 `.claude/databases/<source_key>/` 包，根下source.json登记来源，`query-specs/<domain>/` 放该库各业务域资产；当前目标包是schoolDoubleHigh/query-specs/hpm/。后续新库用独立source_key，当前只整理这一个实际来源；不再另设顶层data-sources/和query-specs/。
域内semantics/维护字段、关联、期间与口径，metrics.json维护指标，rules.json维护可执行计算规则，catalog.json登记模型可读文档与查询索引，specs/、sql/、tests/维护查询和验证，coverage.json保留业务覆盖。指标实例批量查询，不生成几千份静态SQL；同名指标在不同库独立核验，不自动等价或混用。
source.json的profiles路径相对数据库包根；catalog的文档/spec_file、QuerySpec的sql_file相对业务域根；人工evidence仍相对仓库根且不进入Prompt；模板内部路径相对模板根。解析后校验边界、软链接和文件类型，拒绝跨包引用；模型只传标识，不能提供资产路径。
连接信息移出database-qa工作流，由CCSDK_DATA_CONFIG指定受保护JSON，内含connections和policies两个映射；配置路径相对值以仓库根为基准，其内部文件引用相对配置父目录。密钥只用每连接独立的env/Secret引用，不进入数据库包、Prompt或Git。

## 最小字段

HTTP字段继续camelCase，内部字段和工具名用snake_case；用户指定的标识值schoolDoubleHigh大小写敏感，保持原样，不自动改名。下列新增字段为拟议契约，未列为可选则必填；只实现静态配置及解析函数，不建设绑定规则引擎或配置中心。

| 对象 | 字段 / 类型 | 作用 |
| --- | --- | --- |
| Source / source.json | source_key:string, name:string, profiles:object, connection_ref:string, policy_ref:string, version:int, enabled:bool | source_key必须等于包目录名，使用稳定标识，不是物理库名；profiles如hpm -> query-specs/hpm；每来源独立连接/策略引用 |
| Connection / 受保护配置 | connection_ref:string, driver:string, host:string, port:int, database:string, username_ref:string, password_ref:string, tls:object, revision:int, limits:object | 首期mysql+pymysql；TLS校验身份；limits登记连接/查询超时、池大小及全实例并发限制；换地址不改模板 |
| SingleTenantPolicy / 受保护配置 | policy_ref:string, mode:string=single_tenant, source_key:string, tenant_id_ref:string, data_tenant_id_ref:string, capability_refs:string[], template_keys:string[], datasets:object, allowed_queries:string[], dynamic_sql_enabled:bool, project_scope:object, revision:int | 每来源一份策略；JWT租户与业务表租户键分别解析，不默认相等；datasets按domain登记表/列/函数白名单，allowed_queries使用domain/query_id，空集合拒绝固定查询 |
| project_scope / 策略内部 | mode:all_school/selected_projects, project_ids?:string[] | all_school仅在管理员确认当前使用者可读该登记学校范围时启用；selected_projects必填非空集合，空集合拒绝；不预设所有用户有全库权限 |
| DataContext / 每Run内部 | run_id:string, tenant_id:string, user_id:string, capability_ref:string, policy_revisions:object | tenant/user来自已验Run JWT；权限修订按source_key记录；服务端传Worker和执行器，模型不能覆盖，不放进业务payload |
| ResolvedAccess / 每来源解析结果 | source_key, source_version, policy_revision, connection_ref, connection_revision, data_tenant_id, project_scope, allowed_datasets, allowed_queries, dynamic_sql_enabled, access_fingerprint | 固定和动态查询共用；解析失败即拒绝；租户、来源、账号/权限版本进入指纹，不把校双高库的权限或业务租户键复用到另一库 |
| Catalog / catalog.json | version:int, documents:string[], queries:object[] | 文档显式登记且限定域内semantics/；查询索引保留id/name/description/status/spec_file，来源由包确定；未登记文档不进模型 |
| QuerySpec / 域内specs/ | 保留id/version/status/parameters/output/requires_queries；移除source_keys，由包确定来源；增加checks与batch | requires_queries默认只解析同库同域；跨库组合由计划声明完整QueryRef；checks须已实现，batch声明数组参数/结果键/合并维度；保留旧验证范围 |
| Metric / metrics.json | metric_key, name, aliases, kind, grain, unit, period_modes, query_ref或rule_ref | direct引用query_id+输出字段；derived引用规则及其依赖；全局定位用source_key+domain+metric_key |

登记示意：`{"source_key":"schoolDoubleHigh","name":"校双高数据库","profiles":{"hpm":"query-specs/hpm"},"connection_ref":"schoolDoubleHigh_primary","policy_ref":"schoolDoubleHigh_readonly","version":1,"enabled":true}`。目录与版本由服务端核验，各库使用自己的标识/连接/策略；模型和模板仍以(source_key,domain,query_id)引用。

## 单租户执行与扩展边界

保留现有Run JWT身份与Java的Capability/文件授权。Python拒绝不匹配所配置租户的请求，通过resolve_data_access(context, source_key)验证静态策略、来源/模板/能力和查询范围；本期不引入Java Data Grant回调或逐次远程权限请求。静态策略需由业务授权方确认，已有部门/项目差异不能静默扩大。
单租户是部署策略，不能删tenant参数、合并用户会话或用默认租户兜底。固定QuerySpec仍使用可信data_tenant_id及项目范围；实际SQL有tenant_id_字段就保留过滤。同一物理库是否还含其他租户行属于数据核验事项，不由“当前只有一个数据库”推出。
连接选择单独放resolve_connection(context, source_key)；本期读取source.connection_ref，未来可按(context.tenant_id, source_key)查连接映射。execute_query_spec/execute_readonly_sql及模板只依赖ResolvedAccess，不直接读环境变量或拼库名。
结果/证据记录从第一天带tenant_id、user_id、run_id、source_key、access_fingerprint；读取同时核验归属，实际工作目录仍沿RunStore受控根解析，不靠文件名保权限。默认不跨Run缓存；未来缓存必须包含租户/权限指纹、参数和版本，不能只用query_id。
连接池按租户、来源、连接/凭据修订及有效范围分组，结束回滚清理，轮换废弃旧池；不使用进程全局current_tenant或临时修改os.environ。应用只部署一个租户时这些仍是普通参数和字典键，不引入多租户调度平台。

## 数据库与报告工具

统一data MCP供问数/撰写使用，首期所有来源使用同一工具集合；source_key必填，当前取schoolDoubleHigh，未来可选获准来源，不使用默认库回退。不暴露DSN/密码，不要求显式connect。HTTP模板payload仍只传templateKey，报告年份/要求放input.text。

| 工具 | 主要入参 | 返回 / 约束 |
| --- | --- | --- |
| list_data_sources | query?, cursor? | 首期遍历获准且启用的来源，返回标识/名称/域/范围/状态；当前仅schoolDoubleHigh，不硬编码单条返回 |
| describe_data_source | source_key, domain?, topics?, datasets? | 按需返回该库域的字段、口径、可用指标、查询及动态SQL状态；不全量注入Prompt |
| resolve_entities | source_key, domain, entity_type, query, parent_ref?, cursor? | 校双高库项目/任务/指标的业务名称及不透明entity_ref/scope_ref；同名必须消歧 |
| find_query_specs | source_key, domain, intent?, metric_key?, cursor? | intent/metric_key至少一项；返回query_id、定义/参数/输出/状态，版本由服务端固定 |
| execute_query_spec | source_key, domain, query_id, parameters, scope_ref?, entity_refs? | 固定SQL和依赖检查；模型只填业务参数，租户和授权键由Context/引用解析注入 |
| execute_readonly_sql | source_key, domain, sql, parameters, purpose, scope_ref? | 模型生成SQL，值用:name绑定，表列必须来自describe；结果标dynamic，不自动改写指标库 |
| read_query_result | result_ref, cursor?, columns?, page_size? | 读取物化结果授权页，不重复执行SQL；返回结构和来源/期间/完整性/证据 |
| prepare_report_data / get_report_data / render_report | 同[模板计划](template-batch-data-plan.md) | reports工具按模板组织批量取数、章节事实和校验填表，复用查询与DOCX基础能力；模板角色hpm绑定schoolDoubleHigh |

调用示例：`{"source_key":"schoolDoubleHigh","domain":"hpm","query_id":"fund_totals","parameters":{"year":"2025"},"scope_ref":"scope_selected"}`。scope_selected由当前Run定位，不接受真实tenant_id；内部QueryRef统一(source_key,domain,query_id)，避免同库不同域查询重名。

## 执行实现与只读范围

沿用ADR-021的SQLAlchemy Core 2.x+PyMySQL执行建议，SQLGlot用于AST解析；参数绑定、连接池和事务交给成熟库。本地DBHub 1.2.0通用execute_sql仅接SQL，自定义参数工具需预注册；新执行器完成问数回归后直接替换旧DBHub装配和无其他使用方的依赖，不长期并行两套后端。
本期沿用python/tools/docx.py的SDK进程内MCP注册模式，data工具调用通用executor；一次性与持久Worker均在每个Run前接收不可变DataContext，工具调用时捕获本轮上下文，完成/取消先清理后台任务再清除上下文。Actor仍串行；凭据/权限指纹变化重建工具配置，不能把第一轮上下文永久闭包绑定。此模式不宣称构成生产沙箱。
工具规范：data.py/create_data_server和reports.py/create_reports_server使用sdk_tool、create_sdk_mcp_server注册；工具名为 `mcp__data__<name>` 或 `mcp__reports__<name>`，不按库/模板生成新工具名。tools只校验和封装，业务执行放data_access/reporting；所有新工具声明JSON Schema、必填/可选/枚举/上限，未知顶层参数拒绝，parameters按QuerySpec再次校验。
返回使用MCP内容中的结构化JSON，保留status、引用和warnings；执行失败设置isError并返回error的code/message/retryable，不把异常/凭据原文输出。计划queued/blocked、空结果与执行失败分别表达；后台任务归属Run并响应取消，登记mcp_auth和按能力的明确工具白名单，不能仅靠Prompt限制调用。
固定查询：解析授权 -> 来源/版本/字段检查 -> requires_queries诊断 -> SQLAlchemy驱动绑定 -> 只读事务 -> 输出/完整性校验。nullable参数缺失与显式null分开；数组参数需声明expanding，空列表不扩大范围；多项目金额等只能按QuerySpec登记可加性汇总。
动态查询：只允许单条SELECT或只读WITH，检查所有子查询/CTE/UNION的表列函数；限定当前source登记的库与对象，拒绝跨库SQL、写操作、多语句、锁、系统表、文件/网络函数和未知语法。SQL解析不代表业务口径已验证，动态结果的期间/粒度无法证明时返回unknown。
当只读账号可访问的数据完全位于当前学校已授权范围时，单租户无需额外按用户建视图即可开放动态SQL；仍只开放登记表列。若账号还可读其他租户或用户未获准项目，须数据库侧缩小权限/视图后开放，或仅执行审查过的固定SQL；不凭模型补WHERE来声称完成隔离。
模型可用动态SQL补充分析；填固定模板仅允许已登记dynamic_policy且通过语义/期间/输出校验的槽位。不得因来源统一就绕过评分、成果去重和历史快照缺口，不自动以“最新反馈”填历史年度。
数据库端超时与应用超时分别实现；取消需终止SQL并核验，不确定的连接废弃。校双高库一组查询使用同一只读一致性事务，物化完释放连接；撰写不占事务。建议初始连接超时10秒、查询30秒、池2个、全实例并发受限，取数计划/结果上限配置化且经压测调整。
模型/普通日志不接收连接凭据和业务Token；data不注入业务Token，business MCP继续REQ-001逐请求注入。当前bypassPermissions仍允许宿主资源访问，多租户生产前必须完成工具白名单及文件/进程/网络隔离，不把本期单租户便利当多租户验收。

## 管理与结果

一期即提供按source_key执行的list/validate/test-connection/verify-source管理命令、启停及整包版本回滚；使用python/data_access/__main__.py命令入口，仅管理员调用。管理多份来源登记、连接与策略，当前只配置schoolDoubleHigh；校验含真实表/列/字典和独立基准，新增来源不是复制Workflow。
catalog.py启动时扫描databases/*/source.json，校验目录键、重复标识、profiles/文档/查询引用及启用来源的连接/策略存在，再建立内存索引；不自动执行SQL或将全部资产注入模型。workflow.json声明data_sources候选列表，如 `["schoolDoubleHigh"]`，与来源策略的Capability授权取交集；目录存在、enabled=true均不单独授予权限。
以数据库包版本及内容摘要固定每次Run使用的资产；发布采用校验后的整包替换和服务重启，首期无热更新/配置中心/管理平台。各来源的启停、权限和连接修订分别处理，停用或收权阻断后续执行及结果交付；新Run才能使用更新后的资产版本。
结果统一为status、result_ref、source_key、domain、query_id/version、columns、row_count、preview、period、scope_ref、snapshot_ref、complete、warnings、evidence_refs。preview最多20行，分页上限200行；row_count仅为物化结果数，complete不代表业务字段齐全；超量/截断不能填完整报表。
Decimal用十进制字符串+列类型，NULL/无记录/0分开；原始行、动态SQL与参数仅放受限Run结果目录，结果引用不可跨用户/租户访问。内部ID转不透明引用，对外保留业务名和证据；保留期与Run归档一致，不入Git。

## 基于现有代码的实施顺序

1. 资产集中：创建databases/schoolDoubleHigh/source.json；把当前query-specs/hpm/的catalog、specs、sql、coverage及测试移入schoolDoubleHigh/query-specs/hpm/，database-qa公共semantics迁入该域。拆sources.json为来源登记、部署连接/策略和域字典；移除catalog/spec的source_keys，更新模板QueryRef及evidence路径，保留32项各自的验证范围和待核验状态。替换加载方后删除旧资产目录/语义副本和旧source键，不保留别名层。
2. 身份与配置：server.py的_internal_worker_payload增加由claims生成的DataContext；runtime/config.py按workflow.data_sources和来源策略装配data工具，替换_workflow_database/create_database_mcp_server。workflow_prompt_documents保留流程文档边界，公共语义改由data_access/catalog按授权显式加载；agent_worker/session_actor逐Run绑定/清理，protocol.py业务请求不新增tenant/connection字段。
3. 查询执行：新增python/data_access/{__main__,context,catalog,access,connections,executor,sql_policy,results}.py及python/tools/data.py；先跑固定/动态SQL及两份隔离合成库，再跑已有18问。业务知识留包内；mcp_auth登记data和reports不接业务Token，测试工具Schema、未知参数、错误返回、凭据和取消边界。
4. 模板计划：新增python/reporting/{bindings,planner,rendering}.py和reports工具；保留writing-docx的agent/Client及writing-documents Skill入口，补固定模板计划分支与template.json/slots。同步Skill和工具白名单：固定模板走报告计划，普通写作沿原文稿流程，数据库问数保持direct；先验证代表性表/正文再覆盖40表，不按模板复制Workflow。
5. 部署与验收：同步依赖、deploy/compose.database.yaml、deploy.sh及write-env.py；改挂CCSDK_DATA_CONFIG，数据库包随镜像交付、密钥不入镜像。更新资产测试BASE/ROOT及旧report_db断言，验证双库同名查询/指标、交叉结果引用、禁用/缺连接、路径越界、权限和凭据轮换；更新18问/40表基准及README/ARCHITECTURE。

## 以后扩展多租户

首期多库与以后多租户是两个维度：当前仅schoolDoubleHigh，未来同一租户可登记其他source。以后access.py扩为Java授权或受控租户表，connections.py按tenant_id+source_key选连接；相同schema/口径可复用数据库包，差异须分别核验，目录不按租户复制。模板/工具引用保持不变，各租户每来源策略分别检查。
共库按tenant_id隔离需另做数据库侧行级防护、只读账号/视图及动态SQL绕过回归；不能只改一个开关或追加WHERE。并发额度、连接轮换、结果与Client隔离都需两租户同业务ID测试。保留上述边界降低重构范围，不承诺多租户无需实施和验收。

## 工程要求检查

| 要求 | 状态 | 依据 | 差距与后续处理 |
| --- | --- | --- | --- |
| REQ-001 | 部分满足 | 业务Token继续按MCP注入，data不接收；DataContext只含可信身份 | 凭据轮换、每Run上下文、隔离与真实Java链路待实现验收 |
| REQ-002 | 部分满足 | templateKey/Capability契约不变；单租户静态来源授权，执行资产服务端解析 | 模板及范围校验未实现；静态策略不覆盖真实细粒度ACL时须接Java授权，不能默认全库可读 |
