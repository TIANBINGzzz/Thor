# 模板数据源最小标注规范

## 目标

让模型知道“填什么、从哪取、取哪个字段”，同时避免为每个段落重复写 SQL。标注服务于预制模板和上传模板；数据库连接仍由运行时配置管理，模板只引用业务数据源。

## 三层标注

### 1. 模板层

`template.json` 只声明模板身份、能力、参数和来源角色：

```json
{
  "template_key": "szpt-midterm",
  "source_roles": {"hpm": "schoolDoubleHigh"},
  "parameters": ["years", "as_of", "period_mode"]
}
```

`source_key` 是业务数据源标识，不是数据库连接名。模板不得保存 DSN、密码或宿主机路径。

### 2. 数据集层

在模板的 `query-bindings.json` 中，每种可复用数据只登记一次。必须包含 `dataset_key`、`source_role`、`domain`、`query_id`、参数绑定、适用范围和输出用途。`query_id` 指向 `.claude/databases/<source_key>/query-specs/<domain>/specs/` 中的 QuerySpec；SQL 只维护在 QuerySpec 内。

```json
{
  "dataset_key": "group_a_task_progress",
  "source_role": "hpm",
  "domain": "hpm",
  "scope_role": "group_a",
  "query_id": "task_progress_summary",
  "parameter_bindings": {
    "year": {"from": "report_parameter", "key": "years", "expand": "each"},
    "level": {"from": "literal", "value": 3}
  },
  "purpose": "专业群三级任务进度与完成率"
}
```

### 3. 槽位层

只有动态位置需要补充来源；静态表头和固定概括文字不标。槽位只引用数据集和输出字段，不重复来源、表名或 SQL：

```json
{
  "slot_key": "T03_R002_C05_P01",
  "kind": "scalar",
  "name": "完成值",
  "dataset_key": "group_a_task_progress",
  "field": "completed_count",
  "unit": "条",
  "binding": {"selector": {"task_code": "指标编码"}},
  "missing_policy": "highlight_and_ask"
}
```

叙述段落只需写 `evidence_datasets: ["group_a_task_feedback"]`，并在 `write_instruction` 说明“基于已审核反馈概括”；模型不得把反馈条数直接当成果数量。无法确定字段时使用 `status: needs_confirmation`，不要猜 QuerySpec 或生成未经定义的 SQL。

## 低工作量标注流程

1. DOCX 解析器自动生成 `slot_key`、章节、表/行/列/段落定位和原文；静态位置自动标记为 `static`。
2. 对数字、日期、比例、待补材料和需要事实依据的段落生成待标注清单，按标题相似度、章节和范围合并成组。
3. 标注人员每组选择一个已有 `dataset_key` 和 `field`；同一查询的几十个位置只做字段映射。
4. 运行前校验 `source_key -> domain -> query_id -> field` 链路、粒度、单位、期间和范围；校验失败的槽位留空并高亮/询问。
5. 计划器按数据集去重查询，结果按 `field` 回填槽位并记录 `result_ref` 作为证据。

## 上传自定义模板

上传模板先生成临时槽位清单，不立即修改预制模板。模型根据标题和上下文提出数据集候选；已确认的引用现有 QuerySpec，未确认的标为 `needs_confirmation`。用户确认后生成该模板自己的 `template.json` 与 `query-bindings.json`，仍复用相同数据源目录和工具。

## 与现有实现的对应关系

- 模板和数据集由 `python/reporting/planner.py` 读取并按数据集编译查询节点。
- 槽位由 `python/reporting/planner.py` 的 `_slots` 按 `dataset_key + field` 回填。
- 数据访问通过 `mcp__data__*` 工具和 `python/data_access/` 执行；模型不接触连接凭据。
- 当前 `szpt-midterm` 的主要缺口是动态槽位仍只有宽泛的 `evidence_datasets`，需要逐组补 `dataset_key`/`field`，而不是继续扩写来源 Markdown。

## 工程要求检查

| 要求 | 状态 | 依据 | 差距 |
| --- | --- | --- | --- |
| REQ-001 | 满足设计约束 | 连接凭据留在运行时；模板只引用 `source_key` | Java 透传和生产凭据隔离仍需端到端验收 |
| REQ-002 | 满足设计约束 | 模板由内部能力映射加载；上传模板生成内部资产 | 自定义模板注册和授权控制尚未实现 |
