# 数据库包

当前唯一来源是校双高数据库，标识固定为 `schoolDoubleHigh`。`hpm` 是项目、任务、资金和绩效业务域。新增数据库以相同目录结构单独登记，工具名称不变。

| 目录或文件 | 职责 |
| --- | --- |
| `<source_key>/source.json` | 来源名称、启停、版本和连接/策略引用；没有凭据 |
| `query-specs/<domain>/catalog.json` | 该域查询索引、可读取的语义主题和实体解析入口 |
| `semantics/` | 公共业务术语、字段、关联、粒度和期间口径，供问数和撰写按需读取 |
| `metrics.json` | 查询输出字段对应的指标及单位；同名指标按库和域分别定位 |
| `rules.json` | 未定义计算规则的明确登记；不把进度当得分 |
| `specs/` | 参数、输出、状态、依赖和检查声明 |
| `sql/` | 使用 `:name` 参数的固定只读查询 |
| `coverage.json` | 原18问及已核验业务表的覆盖关系 |
| `tests/` | 合成数据口径回归；历史来源核验资料只供维护者查看 |

运行入口为 `python/data_access/`，数据工具在 `python/tools/data.py`。模板只引用 `source_key + domain + query_id`，不拼物理库名。业务 Token 不注入 data/reports。

查询共33项：26项defined、1项blocked、6项needs_definition。保留旧verification.qa_db/report_db作为历史证据，不作为当前来源别名或新核验结论。已定义不等于模板全部业务值可用。

连接和访问策略放 `CCSDK_DATA_CONFIG` 指向的受保护JSON；相对路径以仓库根为基准，密钥文件及CA路径以配置文件目录为基准。示例见 `deploy/data-access.example.json`，空用户或空项目列表拒绝访问。不得将本地文件路径、租户值、主键或真实数据写入本目录。

管理命令从仓库根执行：

```text
python -m unittest discover -s python/tests -t python -p "test_*.py"
```

来源管理命令在python/下执行：`python -m data_access list`；配置路径仍以仓库根为基准，validate/probe参数以--help为准；参见deploy/data-access.example.json。

真实库零行投影已核验23项输出结构和原SQL一致；该核验不证明完整报告数据、历史适用版本或生产授权链路通过。
