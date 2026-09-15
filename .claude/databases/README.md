# 数据库包

当前唯一来源是校双高数据库 `schoolDoubleHigh`，`hpm` 为项目、任务、绩效和资金业务域。

| 位置 | 唯一职责 |
| --- | --- |
| `<source_key>/source.json` | 来源标识、启停、版本、可用Capability、私有连接入口、域知识路径和实体解析 |
| `private/connection.json` | 实际连接和访问策略；用户名、密码通过env/file引用；本机配置不入Git或镜像 |
| `schema/<domain>.json` | 核验过的表、列、类型、字段说明、函数及内部列；校双高当前13表158列 |
| `metrics/<domain>/<id>.json`及同名`.sql` | 指标/查询定义、参数、输出和只读SQL；当前26项可执行定义 |
| `metrics/<domain>/pending.json` | 7项缺定义/禁用原因，防止模型用其他口径替代；没有占位SQL |
| `semantics/business.md` | 默认口径、单位、期间、两棵指标树和报告事实来源 |
| `semantics/relationships.md` | 实体关联、归属和去重 |

模型只调用data工具；连接文件、授权策略和秘密不进入模型上下文。工具按需提供库表和语义，指标通过名称/别名检索，`metric_key=query_id.field`定位公开输出。新增数据库在自己的source.json绑定能力，工作流不枚举数据库名。

`python/data_access/`处理连接、授权、检索、执行和结果；`python/runtime/data_services.py`装配每Run服务；固定模板代码在`python/workflows/writing_docx/`。数据库测试和18问覆盖在`python/tests/databases/school_double_high/`，运行数据在Run目录。

每Run冻结已登记知识和私有配置的独立副本；私有文件不计入知识版本，连接/策略版本单独记录。授权来源仍校验tenant、用户、Capability、模板和项目范围。来源发现不授予权限，data/reports不接业务Token。

连接示例见`deploy/data-access.example.json`，部署时放到source.json登记的private/connection.json；秘密与CA相对该文件解析。管理员可在python目录执行`python -m data_access list/validate/probe`，无需Workflow环境变量或全局连接索引。生产Java授权、撤销和多租户隔离仍须独立验收。
