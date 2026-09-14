SELECT p.id_ AS project_id, p.name_ AS project_name, COUNT(m.project_id_) AS module_count,
       MIN(m.performance_stage_flag_) AS stage_flag,
       COUNT(DISTINCT m.performance_stage_flag_) AS distinct_flag_count
FROM t_hpm_project p
LEFT JOIN t_hpm_project_module m ON m.tenant_id_ = :tenant_id
  AND m.tenant_id_ = p.tenant_id_ AND m.project_id_ = p.id_ AND m.delete_flag_ = '0'
WHERE p.tenant_id_ = :tenant_id AND p.delete_flag_ = '0' AND p.high_flag_ = '1'
  AND (:project_id IS NULL OR p.id_ = :project_id)
GROUP BY p.id_, p.name_
ORDER BY p.id_
