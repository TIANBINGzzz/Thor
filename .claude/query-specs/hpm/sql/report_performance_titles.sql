SELECT perf.project_id_ AS project_id, perf.id_ AS performance_id, perf.name_ AS performance_name,
       first_item.name_ AS first_title, second_item.name_ AS second_title,
       perf.target_value_ AS current_target_value, perf.finish_value_ AS current_finish_value,
       perf.progress_ AS current_progress
FROM t_hpm_project_performance perf
JOIN t_hpm_project p ON p.tenant_id_ = perf.tenant_id_ AND p.id_ = perf.project_id_
LEFT JOIN t_hpm_project_performance first_item ON first_item.tenant_id_ = :tenant_id
  AND first_item.tenant_id_ = perf.tenant_id_ AND first_item.project_id_ = perf.project_id_
  AND first_item.id_ = perf.first_item_id_ AND first_item.delete_flag_ = '0'
LEFT JOIN t_hpm_project_performance second_item ON second_item.tenant_id_ = :tenant_id
  AND second_item.tenant_id_ = perf.tenant_id_ AND second_item.project_id_ = perf.project_id_
  AND second_item.id_ = perf.second_item_id_ AND second_item.delete_flag_ = '0'
WHERE perf.tenant_id_ = :tenant_id AND perf.delete_flag_ = '0' AND perf.level_ >= 3
  AND p.tenant_id_ = :tenant_id AND p.delete_flag_ = '0' AND p.high_flag_ = '1'
  AND perf.project_id_ = :project_id AND perf.id_ = :performance_id
