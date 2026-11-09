# 数据库资产与查询边界

当前唯一来源为校双高 `schoolDoubleHigh`，`hpm` 是项目、任务、资金和绩效业务域。来源标识不是物理库名或租户名；统一命名不代表全部历史、评分和报告数据已核验。

## 资产与装配

| 位置 | 权威内容 |
| --- | --- |
| `.claude/databases/<source_key>/source.json` | 来源标识、版本、启停、域知识路径和实体解析 |
| `schema/<domain>.json` | 已核验表列、类型、说明、函数、内部字段及强制隔离用tenant_column |
| `metrics/<domain>/*.yaml` | 主题指标定义、共享参数、输出、SQL、语义及校验；pending 只记录未定义原因，不造占位 SQL |
| `semantics/business.md`、`relationships.md` | 默认口径、单位、期间、实体关系和去重 |
| Nacos `databases` | 客户连接、数据租户范围与查询预算，字段及路径基准见 [配置说明](../../config/README.md)；不放入知识包或能力环境文件 |
| `python/data_access/`、`runtime/data_services.py` | 通用执行与每 Run 装配；资产测试在 `python/tests/databases/` |

Capability 在 capability.json 中以 data.access=required/optional 和 data.sourceRefs 声明数据需求及来源，模板按 source_key/domain/query_id 引用业务知识，不复制 SQL。新增来源复用同一套工具，发现来源不授予权限。

普通会话不加载数据库；普通撰写允许未配置数据库，但配置损坏须失败；问数和预制模板要求所需来源连接可用。部署启动冻结客户配置；每 Run 冻结已登记资产及私有配置副本，记录资产/查询摘要及客户范围指纹；来源按可信能力装配，SDK 环境不接收连接秘密。

## 字段与配置

资产格式以 source.json、主题 YAML 和 catalog.py 校验为准，不另抄一份全部字段。QuerySpec 的 id 即 query_id，metric_key 使用 query_id.field 定位公开输出；参数只描述业务输入，租户和内部对象键由可信上下文注入。

一个 tenantId 对应一个客户，一客户一套 Runtime、数据库和服务地址。同客户所有 usercode 查询同一业务数据。Run JWT 只绑定本次执行、用户、会话和文件归属，不在 Nacos 固定 Runtime tenantId；数据库 self 每轮从 Java 认证后透传的业务 Token 解析，缺失或非法时拒绝访问。用户授权、业务验签和撤销仍由 Java 负责。

Nacos 每来源分 connection/access/query；access.tenantIds 默认仅 self。额外测试租户的环境授权和退出要求见[REQ-001](engineering-requirements.md#req-001业务-token-透传与按-mcp-注入)，生产模板仍仅 self；该范围只作用于选中数据源，不扩大 Runtime 或其他业务系统身份。表列、函数和指标范围由 Catalog 派生，不重复配置 Capability/模板清单或 selected 项目授权。项目/任务仍可作为业务筛选条件，引用仅本轮有效。TLS 默认校验 CA 与主机身份，显式 disabled 不自动降级；字段和路径基准见[配置说明](../../config/README.md)。

## 查询边界

- 模型仅调用 `mcp__data__*`，参数用 snake_case；HTTP 仍用 camelCase，schoolDoubleHigh 保持大小写。具体工具 Schema/返回字段以 [data 工具](../../python/tools/data.py) 为准，失败返回 isError 及安全错误码。
- 双高数据库访问要求业务 Token 以解析 self，不向数据库驱动注入 Token，不自行替代 Java 的验签和撤销；校园 Service 仍按自身声明透传本轮 Token。Token 不写入 Prompt、结果或 SDK 配置。
- 按获准来源发现/描述、实体解析、定义检索、查询执行及结果分页使用；scope_ref、entity_ref、result_ref、cursor 仅限所属 Run，不能跨用户或续轮复用。
- 固定/动态SQL均经SQLGlot完整AST检查，执行前把每个物理表包为本次所选学校 scope 的租户过滤子查询；覆盖JOIN、CTE、UNION及嵌套查询。缺tenant_column或白名单表不含该列时拒绝，租户参数只由本轮业务身份和可信数据源范围解析注入。SQLAlchemy绑定参数，在只读一致性事务中执行；输出顺序须匹配定义，NULL、无记录、0、失败及截断分别表达。
- 动态 SQL 须启用 query.dynamic_sql_enabled，并使用客户全量 scope_ref；项目引用只用于固定查询的业务筛选，不把任意 SQL 结果冒充项目统计。删除 database_scope_enforced/scope_source_key 部署声明，保留真实只读账号及 AST 隔离。
- 动态查询拒绝跨库、写入、锁、星号、系统对象、未知列/函数和内部键输出；值用 :name 绑定。未知历史/评分口径不能因允许动态 SQL 而编造。
- 结果含来源、域、资产/查询版本、公开参数、采集时间和动态标记，不含身份/连接秘密；物化结果按 Run 隔离，分页不重复执行 SQL。取证完成后不在模型撰写期间保持数据库事务。
- 取消关闭活动 MySQL socket 或中断 SQLite，连接及执行有预算。Run 内串行、NullPool 无共享连接池；全实例限流、账号总额度和跨库一致性不能由局部限制推导。

## 维护与验收

在 python 目录用 `python -m data_access list/validate/probe`，参数见 --help；知识校验不等于真实连接成功。配置变更后排空任务并重启，配置从 Nacos 读取，无需重建镜像；当前没有数据库管理网页或连接热更新，后续管理方案不能作为已实现能力。

指标登记前用只读实库及独立基准核对 SQL、输出、对象、期间和异常语义；已定义项不因空结果失去来源依据，未定义项不因工具成功而升级。原始数据留忽略目录，必要来源确认见 [来源核验](../verification/report-source-audit.md)。

REQ-001部分满足：数据范围按来源配置并逐Run解析业务JWT，凭据仍逐Run隔离；真实Java认证、撤销及全链路日志尚待验收。REQ-002部分满足：受控来源/模板/能力装配及SQL客户范围强制已接入；Java ACL及生产隔离仍须端到端验收。
