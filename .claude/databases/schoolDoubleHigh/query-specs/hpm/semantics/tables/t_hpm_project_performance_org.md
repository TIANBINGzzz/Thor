# t_hpm_project_performance_org

粒度：绩效指标与负责主部门关系，一对多。该表**没有** `delete_flag_`。

核心字段：`tenant_id_`、`project_id_`、`performance_id_`、`main_org_id_`、`main_org_code_`、`main_org_name_`、`sort_`。

按部门统计绩效时使用 `main_org_*`，关联必须带租户、项目和绩效 ID；不要把人员部门或任务部门替代绩效负责部门。
