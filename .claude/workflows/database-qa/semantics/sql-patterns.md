# SQL 模式

以下模式来自 DBProcessing 的已核验标准 SQL，作为生成器参考；必须根据用户问题补充或删减条件，不能把示例中的实际参数值写入 SQL。

## DBHub 最小调用协议

对任一问题，先且只先调用一次 `mcp__db__search_objects` 检查相关字段。查询任务字段时固定传入：`object_type="column"`、`schema="test_hpm_dev"`、`table="t_hpm_project_task"`、`detail_level="summary"`。只传 `table` 时 DBHub 必须同时传 `schema`；不要先查表摘要再查字段，也不要做缺少 `schema` 的字段查询。

`execute_sql` 不支持 `:tenantId` 等命名参数。需要租户条件时，先从相关主表以最小 `SELECT DISTINCT tenant_id_` 查询确认当前数据源只有一个候选值；实际值只可用于后续 SQL，不得出现在回答、证据、表格或限制中。

## 名称解析

项目名称：在有效国双高项目中按 `name_ LIKE CONCAT('%', :projectNameKeyword, '%')` 查询候选并检查唯一性。指定项目后的年度才在该项目的有效阶段中按 `name_ = :year` 解析。部门名称优先从有效国双高任务的 TaskOrg.main_org_name_ 解析。

## 年度任务层级

```sql
SELECT t.level_, COUNT(*) AS task_count
FROM t_hpm_project_task t
JOIN t_hpm_project_stage s
  ON s.tenant_id_ = t.tenant_id_
 AND s.project_id_ = t.project_id_
 AND s.id_ = t.stage_id_
WHERE t.tenant_id_ = :tenantId
  AND s.tenant_id_ = :tenantId
  AND t.delete_flag_ = '0' AND s.delete_flag_ = '0'
  AND t.high_flag_ = '1' AND t.stage_id_ IS NOT NULL
  AND s.name_ = :year
GROUP BY t.level_
ORDER BY t.level_;
```

## 三级任务指标

先构造只含有效国双高、非空阶段任务的 `task_scope`，再过滤 `level_ = 3`，在同一聚合中计算总数、平均进度、阈值数和完成率。Q3/Q6 不得复用三级过滤，需保留所有层级。

只问“三级任务有多少个”时，不要先查总任务数再查三级任务。一次按 `level_` 分组的聚合既可返回三级数量也可完成层级复核：主表为 `t_hpm_project_task`，过滤当前租户、`delete_flag_ = '0'`、`high_flag_ = '1'`、`stage_id_ IS NOT NULL`，按 `level_` 分组并从结果取 `level_ = 3`。不要为此关联项目表。

## 部门任务

先 `SELECT DISTINCT` 任务 ID 与主部门字段的 `org_task`，再按部门聚合。返回部门名称、任务数、完成数、平均进度和排名；任何一个任务多个部门时不能直接对 join 结果 `COUNT(*)`。

## 年度/累计资金

资金必须与有效国双高项目关联；年度资金再与阶段按租户、项目、阶段关联。过滤 `level_ = 1`、有效记录并现场计算 `execute / NULLIF(budget, 0) * 100`。累计资金加 `stage_id_ IS NOT NULL`。

## 绩效

以绩效为主表关联项目和模块，过滤 `level_ >= 3`，依据 `performance_stage_flag_` 选择有阶段或无阶段记录，使用 `progress_ >= 100` 计算达标数和达标率。

## Q16 固定 CTE

Q16 必须保留三个粒度清晰的 CTE：`fund_base`（只筛资金与项目）、`fund_task`（内连接有效任务）、`fund_org`（内连接任务主部门并按资金主键去重），同时返回有效资金数、带任务数、匹配任务数、匹配部门数、覆盖率、可归属部门数和零执行部门数。覆盖率低于 95% 只能回答数据不足和局部诊断。
