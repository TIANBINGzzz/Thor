# 数据库资产与查询边界

当前唯一来源为校双高 `schoolDoubleHigh`，`hpm` 是项目、任务、资金和绩效业务域。来源标识不是物理库名或租户名；统一命名不代表全部历史、评分和报告数据已核验。

## 资产与装配

| 位置 | 权威内容 |
| --- | --- |
| `.claude/databases/<source_key>/source.json` | 来源标识、版本、启停、Capability 绑定、域知识路径和实体解析 |
| `schema/<domain>.json` | 已核验表列、类型、说明、函数及内部字段 |
| `metrics/<domain>/*.yaml` | 主题指标定义、共享参数、输出、SQL、语义及校验；pending 只记录未定义原因，不造占位 SQL |
| `semantics/business.md`、`relationships.md` | 默认口径、单位、期间、实体关系和去重 |
| `config/databases.json` | 连接和授权策略，字段及路径基准见 [配置说明](../../config/README.md)；不放入知识包或 Workflow 环境文件 |
| `python/data_access/`、`runtime/data_services.py` | 通用执行与每 Run 装配；资产测试在 `python/tests/databases/` |

Workflow 只声明 data_access=required/optional，不枚举库名；来源包绑定能力，模板按 source_key/domain/query_id 引用业务知识，不复制 SQL。新增来源复用同一套工具，发现来源不授予权限。

普通会话不加载数据库；普通撰写允许未配置数据库，但配置损坏须失败；问数和预制模板要求所需来源连接可用。每 Run 冻结已登记资产及私有配置副本，分别记录知识、查询、连接与策略版本；配置改变时重建 Client，SDK 环境不接收连接秘密。

## 字段与配置

资产格式以 source.json、主题 YAML 和 catalog.py 校验为准，不另抄一份全部字段。QuerySpec 的 id 即 query_id，metric_key 使用 query_id.field 定位公开输出；参数只描述业务输入，租户和内部对象键由可信上下文注入。

连接/策略按来源键集中，来源、Capability、模板、用户及项目范围取交集。TLS 默认校验 CA 与主机身份，显式 disabled 是部署选择，不自动降级；证书和数据库路径基准见配置说明。

2026-09-20 用户批准的阶段配置为该来源 policy/connection 的 tenant_id="*"、policy.users=all_authenticated，所有已通过 Runtime 鉴权的调用租户共享原业务数据范围；business_tenant_id 仍限制原学校，查询/能力/模板白名单和结果归属仍校验。恢复租户限制须收紧这三处并重新部署，不能把共享来源当作租户数据隔离。

## 查询边界

- 模型仅调用 `mcp__data__*`，参数用 snake_case；HTTP 仍用 camelCase，schoolDoubleHigh 保持大小写。具体工具 Schema/返回字段以 [data 工具](../../python/tools/data.py) 为准，失败返回 isError 及安全错误码。
- 按获准来源发现/描述、实体解析、定义检索、查询执行及结果分页使用；scope_ref、entity_ref、result_ref、cursor 仅限所属 Run，不能跨用户或续轮复用。
- 固定 SQL 使用 SQLGlot 全 AST 检查及 SQLAlchemy 参数绑定，在只读一致性事务中执行；输出顺序须匹配定义。NULL、无记录、0、查询失败及超限截断分别表达。
- 动态 SQL 另需 dynamic_sql_enabled、database_scope_enforced 及对应来源/策略版本一致；数据库账号/视图必须真正约束全部授权范围，不能靠模型补 WHERE 或机械修改版本号。
- 动态查询拒绝跨库、写入、锁、星号、系统对象、未知列/函数和内部键输出；值用 :name 绑定。未知历史/评分口径不能因允许动态 SQL 而编造。
- 结果含来源、域、资产/查询版本、公开参数、采集时间和动态标记，不含身份/连接秘密；物化结果按 Run 隔离，分页不重复执行 SQL。取证完成后不在模型撰写期间保持数据库事务。
- 取消关闭活动 MySQL socket 或中断 SQLite，连接及执行有预算。Run 内串行、NullPool 无共享连接池；全实例限流、账号总额度和跨库一致性不能由局部限制推导。

## 维护与验收

在 python 目录用 `python -m data_access list/validate/probe`，参数见 --help；知识校验不等于真实连接成功。配置变更后排空任务并重启，镜像内配置须重建；当前没有管理网页或热更新，后续管理方案不能作为已实现能力。

指标登记前用只读实库及独立基准核对 SQL、输出、对象、期间和异常语义；已定义项不因空结果失去来源依据，未定义项不因工具成功而升级。原始数据留忽略目录，必要来源确认见 [来源核验](../verification/report-source-audit.md)。

REQ-001 部分满足：data 不接业务 Token，business 按可信规则注入；真实 Java 撤销及全链路日志尚待验收。REQ-002 部分满足：受控来源/模板/能力装配已接入；阶段共享来源、Java ACL 及生产隔离差距继续保留。
