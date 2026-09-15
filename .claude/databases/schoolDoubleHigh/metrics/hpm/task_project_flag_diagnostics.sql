SELECT COUNT(*) AS task_count,
       COUNT(CASE WHEN p.id_ IS NULL THEN 1 END) AS missing_project_count,
       COUNT(CASE WHEN p.id_ IS NOT NULL AND (p.delete_flag_ IS NULL OR p.delete_flag_ <> '0') THEN 1 END) AS inactive_project_count,
       COUNT(CASE WHEN p.id_ IS NOT NULL AND (p.high_flag_ IS NULL OR p.high_flag_ <> '1') THEN 1 END) AS different_flag_count
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
  ))
