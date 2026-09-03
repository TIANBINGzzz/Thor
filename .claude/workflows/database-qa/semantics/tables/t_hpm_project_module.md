# t_hpm_project_module

粒度：项目模块配置，业务上近似一项目一条。有效记录带 `delete_flag_ = '0'`。

| 字段 | 语义 |
|---|---|
| `tenant_id_` / `project_id_` | 租户和项目 |
| `task_flag_` | 是否启用任务模块 |
| `fund_flag_` | 是否启用资金模块 |
| `performance_flag_` | 是否启用绩效模块 |
| `performance_stage_flag_` | `1` 绩效按阶段，`0` 绩效不按阶段 |
| `delete_flag_` | 逻辑删除 |

绩效查询必须关联该表，并按阶段开关选择 `performance.stage_id_ IS NOT NULL` 或 `IS NULL`。
