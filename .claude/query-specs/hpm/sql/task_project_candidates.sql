SELECT t.project_id_ AS project_id, p.name_ AS project_name, p.high_flag_ AS project_high_flag,
       p.delete_flag_ AS project_delete_flag, COUNT(*) AS task_count
FROM t_hpm_project_task t
LEFT JOIN t_hpm_project p ON p.tenant_id_ = :tenant_id
  AND p.tenant_id_ = t.tenant_id_ AND p.id_ = t.project_id_
WHERE t.tenant_id_ = :tenant_id AND t.delete_flag_ = '0' AND t.high_flag_ = '1'
  AND t.stage_id_ IS NOT NULL
  AND (:project_id IS NULL OR t.project_id_ = :project_id)
  AND (:year IS NULL OR EXISTS (
    SELECT 1 FROM t_hpm_project_stage s
    WHERE s.tenant_id_ = :tenant_id AND s.tenant_id_ = t.tenant_id_
      AND s.project_id_ = t.project_id_ AND s.id_ = t.stage_id_
      AND s.delete_flag_ = '0' AND s.name_ = :year
  )) AND (:name_pattern IS NULL OR p.name_ LIKE :name_pattern)
GROUP BY t.project_id_, p.name_, p.high_flag_, p.delete_flag_
ORDER BY p.name_, t.project_id_
