# 指标定义

## 任务

- 默认任务范围：有效、`t.high_flag_ = '1'`、`stage_id_ IS NOT NULL`；指定年度时关联阶段并过滤 `s.name_ = :year`。若为展示项目名称而关联项目，必须检查并披露项目标记不一致，不得静默改用项目标记过滤任务。
- 默认末端任务：`level_ = 3`。Q3 已完成总数与 Q6 已完成无材料例外统计所有有阶段层级。
- 平均完成进度：`ROUND(AVG(COALESCE(progress_, 0)), 2)`。
- 完成率：`ROUND(SUM(progress_ >= 100) / NULLIF(COUNT(*), 0) * 100, 2)`。
- 达到 50%：`progress_ >= 50`；零进度/未填报：`progress_ = 0 OR progress_ IS NULL`。
- 已完成：只看 `progress_ >= 100`，不使用 `state_` 排除终止或提前完成。
- 部门任务：先从 TaskOrg 按任务主键去重，再按 `main_org_*` 聚合。部门排名的默认参考口径为所有真实年度任务平均进度；如用户要求“三级”则加 `level_ = 3`。

## 支撑材料

任务只有存在至少一条有效反馈同时满足 `state_ = '1'`、`attachment_ IS NOT NULL`、`attachment_ <> ''`、`attachment_ <> '[]'` 才有合格支撑材料。Q6 对已完成任务使用 `NOT EXISTS` 统计缺材料数量。

## 绩效

真实绩效指标为有效国双高项目中的 `level_ >= 3` 记录。必须关联有效项目模块：

- `performance_stage_flag_ = '1'`：只取 `performance.stage_id_ IS NOT NULL`。
- `performance_stage_flag_ = '0'`：只取 `performance.stage_id_ IS NULL`。

绩效平均进度使用 `AVG(COALESCE(progress_, 0))`；达标/未达标以 `progress_ >= 100` / `< 100 OR IS NULL`。问“完成率”时同时给平均进度和按条数达标率，避免歧义。

## 资金

资金是树形结构。预算、投入、执行、到位金额默认仅汇总 `fund.level_ = 1`，金额单位为万元；累计问题另加 `fund.stage_id_ IS NOT NULL`。执行率为执行合计/预算合计*100，分母为 0 时不可计算。不要使用冗余 `*_rate_` 字段，比例现场从金额计算。

Q16 部门零执行必须先诊断 `Fund -> Task -> TaskOrg` 的资金主键覆盖率，再按主部门聚合 `COALESCE(SUM(execute_total_money_), 0) = 0`。未挂任务或无法关联部门的资金不归属部门。
