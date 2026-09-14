SELECT perf.project_id_ AS project_id, perf.id_ AS performance_id, perf.stage_id_ AS stage_id,
       perf.parent_id_ AS parent_id, perf.code_ AS performance_code, perf.name_ AS performance_name,
       perf.level_ AS performance_level, perf.target_value_ AS target_value,
       perf.finish_value_ AS finish_value, perf.progress_ AS current_progress
FROM t_hpm_project_performance perf
JOIN t_hpm_project p ON p.tenant_id_ = perf.tenant_id_ AND p.id_ = perf.project_id_
WHERE perf.tenant_id_ = :tenant_id AND perf.delete_flag_ = '0'
  AND p.tenant_id_ = :tenant_id AND p.delete_flag_ = '0' AND p.high_flag_ = '1'
  AND (:project_id IS NULL OR perf.project_id_ = :project_id)
ORDER BY perf.project_id_, perf.level_, perf.code_, perf.id_
