SELECT s.project_id_ AS project_id, s.id_ AS stage_id, s.name_ AS stage_name,
       s.start_time_ AS start_time, s.end_time_ AS end_time, s.current_flag_ AS current_flag
FROM t_hpm_project_stage s
JOIN t_hpm_project p ON p.tenant_id_ = s.tenant_id_ AND p.id_ = s.project_id_
WHERE s.tenant_id_ = :tenant_id AND s.delete_flag_ = '0' AND p.tenant_id_ = :tenant_id AND p.delete_flag_ = '0' AND p.high_flag_ = '1'
  AND (:project_id IS NULL OR p.id_ = :project_id)
  AND (:year IS NULL OR s.name_ = :year)
ORDER BY s.project_id_, s.name_, s.id_
