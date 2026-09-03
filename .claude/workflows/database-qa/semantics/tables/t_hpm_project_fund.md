# t_hpm_project_fund

粒度：资金树的一个节点。有效记录带 `delete_flag_ = '0'`；金额单位为万元。

| 字段 | 语义 |
|---|---|
| `tenant_id_` / `project_id_` / `stage_id_` | 租户、项目、可选阶段 |
| `id_` / `parent_id_` / `full_id_` | 资金节点主键、父节点和路径 |
| `task_id_` | 可选关联任务；Q16 只能由此连接 Task |
| `level_` | 资金树层级，汇总默认只取 `1` |
| `name_` / `code_` | 资金名称和编码 |
| `budget_total_money_` | 预算小计 |
| `investment_total_money_` | 投入小计 |
| `execute_total_money_` | 执行小计 |
| `arrival_total_money_` | 到位小计 |
| `delete_flag_` | 逻辑删除 |

资金没有 `high_flag_`，必须关联有效国双高项目。不要用冗余比例字段；比例由金额和 `NULLIF` 现场计算。累计统计加 `stage_id_ IS NOT NULL`，避免父子和跨年度重复。
