# t_hpm_project_task

粒度：任务树的一个节点，一行一个任务。有效记录带 `delete_flag_ = '0'`。

| 字段 | 语义 |
|---|---|
| `tenant_id_` / `project_id_` / `stage_id_` | 租户、项目、阶段 |
| `id_` | 任务主键，仅内部关联 |
| `master_id_` / `parent_id_` | 总任务和父任务，自关联树 |
| `name_` / `code_` | 任务名称和编码 |
| `level_` | 任务层级，默认末端口径为 3，业务可到 5 |
| `progress_` | 完成进度，已完成统一 `>= 100` |
| `state_` | 状态展示字段，不用于替代完成条件 |
| `high_flag_` | `1` 国双高任务 |
| `weight_` | 权重文本，使用前需转数值并处理异常 |
| `target_value_` / `complete_value_` | 目标值和完成值，可能非纯数字 |
| `calculate_flag_` | `0` 手填、`1` 汇总下级进度、`2` 汇总下级完成值 |
| `stage_type_` | `0` 进度型、`1` 权重型 |

任务统计必须约束 `stage_id_ IS NOT NULL`；Q3/Q6 例外统计所有有阶段层级，其他整体指标默认 `level_ = 3`。
