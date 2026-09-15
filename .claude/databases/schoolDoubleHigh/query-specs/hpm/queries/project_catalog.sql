SELECT p.id_ AS project_id, p.name_ AS project_name, p.start_time_ AS start_time,
       p.end_time_ AS end_time, p.level_name_ AS level_name, p.progress_ AS current_progress
FROM t_hpm_project p
WHERE p.tenant_id_ = :tenant_id AND p.delete_flag_ = '0' AND p.high_flag_ = '1'
  AND (:project_id IS NULL OR p.id_ = :project_id)
  AND (:name_pattern IS NULL OR p.name_ LIKE :name_pattern)
ORDER BY p.name_, p.id_
