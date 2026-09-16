# 数据库包

当前唯一来源是校双高数据库 `schoolDoubleHigh`，`hpm` 为项目、任务、绩效和资金业务域。

| 位置 | 唯一职责 |
| --- | --- |
| `<source_key>/source.json` | 来源标识、启停、版本、可用Capability、域知识路径和实体解析 |
| `schema/<domain>.json` | 核验过的表、列、类型、字段说明、函数及内部列；校双高当前13表158列 |
| `metrics/<domain>/{projects,tasks,performance,funds}.yaml` | 按业务主题组织27项定义，SQL内嵌；每项保留id/name/description/parameters/grain/sql/output/validation |
| 主题YAML的`parameters`与`pending` | 参数类型每主题共享；6项未定义指标留原因及候选来源，无占位SQL；租户由运行时注入 |
| `semantics/business.md` | 默认口径、单位、期间、两棵指标树和报告事实来源 |
| `semantics/relationships.md` | 实体关联、归属和去重 |

模型只调用data工具；连接文件、授权策略和秘密不进入模型上下文。工具按需提供库表和语义，指标通过名称/别名检索，`metric_key=query_id.field`定位公开输出。新增数据库在自己的source.json绑定能力，工作流不枚举数据库名。

`python/data_access/`处理连接、授权、检索、执行和结果；`python/runtime/data_services.py`装配每Run服务；固定模板代码在`python/workflows/writing_docx/`。数据库测试和18问覆盖在`python/tests/databases/school_double_high/`，运行数据在Run目录。

每Run冻结已登记知识和私有配置的独立副本；私有文件不计入知识版本，连接/策略版本单独记录。授权来源仍校验tenant、用户、Capability、模板和项目范围。来源发现不授予权限，data/reports不接业务Token。

所有连接和策略集中在部署侧`databases.json`的`sources.<source_key>`，不放数据库知识包。`CCSDK_DATABASES_FILE`指定文件位置，相对路径以项目根目录为基准，默认`config/databases.json`；CA相对该文件解析。示例见`deploy/data-access.example.json`。管理员在python目录执行`python -m data_access list/validate/probe`；前两者仅检查知识，probe读取集中配置。生产Java授权、撤销和多租户隔离仍须独立验收。
