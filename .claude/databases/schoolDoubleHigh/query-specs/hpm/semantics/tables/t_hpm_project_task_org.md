# t_hpm_project_task_org

粒度：任务与负责部门关系，一对多。该表**没有** `delete_flag_`。

核心字段：`tenant_id_`、`project_id_`、`task_id_`、`org_id_`、`org_name_`、`main_org_id_`、`main_org_code_`、`main_org_name_`。

牵头部门只使用 `main_org_*`。任务可能关联多个主部门，因此聚合前按任务主键和主部门去重，并同时校验租户、项目、任务。
