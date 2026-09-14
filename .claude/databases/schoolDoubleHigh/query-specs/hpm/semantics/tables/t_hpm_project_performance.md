# t_hpm_project_performance

粒度：绩效树的一个指标节点。有效记录带 `delete_flag_ = '0'`。

| 字段 | 语义 |
|---|---|
| `tenant_id_` / `project_id_` / `stage_id_` | 租户、项目、可选阶段 |
| `id_` / `parent_id_` | 指标主键和父指标，自关联树 |
| `first_item_id_` / `second_item_id_` | 回溯一级/二级绩效分类，同tenant/project关联并核验层级；不等于一级建设任务 |
| `code_` / `name_` | 指标编码和名称 |
| `level_` | `1/2` 分类节点；`>=3` 真实可填报指标 |
| `target_value_` / `finish_value_` | 目标值和完成值 |
| `progress_` | 完成进度，达标统一 `>= 100` |
| `state_` | 状态展示字段 |
| `high_flag_` | 不能单独区分国/省，范围以项目标记为准 |
| `delete_flag_` | 逻辑删除 |

绩效查询必须关联项目和模块，按 `performance_stage_flag_` 选择有阶段或无阶段指标。
