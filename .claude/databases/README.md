# 数据库包

当前唯一来源为校双高数据库`schoolDoubleHigh`，`hpm`是项目、任务、绩效和资金业务域。新增数据库单独登记来源和连接策略，复用同一套工具。

| 文件 | 职责 |
| --- | --- |
| `<source_key>/source.json` | 来源名称、域路径、启停、版本、连接/策略引用，无凭据 |
| `query-specs/<domain>/domain.json` | 语义主题和实体解析配置，不重复列查询 |
| `queries/<query_id>.json`及同名`.sql` | 唯一查询定义与参数化只读SQL；文件名即查询标识 |
| `pending.json` | 未定义/禁用项及原因；不可执行，无占位SQL |
| `semantics/schema.md` | 13张表的必要字段含义 |
| `semantics/relationships.md` | 实体关联、去重和归属 |
| `semantics/business.md` | 统计口径、两棵指标树及报告期间来源 |
| `tests/` | 合成回归和18问覆盖；不进入运行快照 |

Python从查询定义生成目录，按名称、别名及中文词对匹配排序；`metric_key=query_id.field`直接定位公开输出字段，不是另一个独立指标库。参数、输出及依赖只维护一份；调用方显式传业务参数，租户/项目键由服务端注入。26项可执行查询，7项明确缺定义或禁用。

`python/data_access/`负责来源授权、连接、检索、执行和结果；`python/tools/data.py`提供MCP入口。每Run冻结已登记运行资产并记录版本，测试/历史材料及未登记文件不影响版本或进入Prompt。模板继续引用`source_key+domain+query_id`，固定批量取数和动态只读SQL共用授权边界。

连接和权限读取`CCSDK_DATA_CONFIG`；相对配置路径以仓库根为基准，秘密及CA相对配置父目录。示例见`deploy/data-access.example.json`。来源发现不授权，单租户仍保留tenant过滤；data/reports不接业务Token。

在python目录执行`python -m data_access list/validate/probe`，参数见`--help`。仓库根回归：`python -m unittest discover -s python/tests -t python -p "test_*.py"`。SQL/结构通过不代表历史业务值完整，生产Java授权及多租户隔离须独立验收。
