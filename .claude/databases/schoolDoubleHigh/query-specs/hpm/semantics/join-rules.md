# 逻辑关联规则

数据库没有物理外键。以下是允许的关联，所有条件都要同时带租户；双方存在项目字段时也带项目条件。

```text
Project -> Stage       s.project_id_ = p.id_
Project -> Module      m.project_id_ = p.id_
Project -> Task        t.project_id_ = p.id_
Project -> Performance perf.project_id_ = p.id_
Project -> Fund        f.project_id_ = p.id_
Stage -> Task/Perf/Fund x.project_id_ = s.project_id_ AND x.stage_id_ = s.id_
Task -> Feedback       tf.project_id_ = t.project_id_ AND tf.task_id_ = t.id_
Task -> Member         tm.project_id_ = t.project_id_ AND tm.task_id_ = t.id_
Task -> Org            tor.project_id_ = t.project_id_ AND tor.task_id_ = t.id_
Task -> Fund           f.project_id_ = t.project_id_ AND f.task_id_ = t.id_
Performance -> Feedback pf.project_id_ = perf.project_id_ AND pf.performance_id_ = perf.id_
Performance -> Org     por.project_id_ = perf.project_id_ AND por.performance_id_ = perf.id_
Task -> child Task     c.parent_id_ = t.id_
Performance -> child   c.parent_id_ = perf.id_
```

`TaskOrg` 和 `PerformanceOrg` 没有 `delete_flag_`。牵头部门只能使用 `main_org_id_`、`main_org_code_`、`main_org_name_`，不能把原始 `org_*` 字段或项目成员主部门替代它。

任务的 `performance_ids_` 与绩效的 `task_ids_` 是 JSON 文本弱关联，不作为常规 join；除非用户明确要求关系核验，不使用字符串匹配建立统计关系。
