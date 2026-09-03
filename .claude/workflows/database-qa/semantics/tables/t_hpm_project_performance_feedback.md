# t_hpm_project_performance_feedback

粒度：一次绩效反馈提交，一对多。有效记录带 `delete_flag_ = '0'`。

核心字段：`tenant_id_`、`project_id_`、`performance_id_`、`create_time_`、`year_target_value_`、`total_target_value_`、`year_complete_value_`、`total_complete_value_`、`progress_`、`total_progress_`、`state_`、`delete_flag_`。

`state_` 为 `0` 提交、`1` 通过、`2` 驳回。反馈是历史提交记录，统计指标本身优先使用 Performance 当前进度；需要反馈时间/年度值时先按业务主键预聚合。
