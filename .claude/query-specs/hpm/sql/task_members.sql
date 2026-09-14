SELECT t.project_id_ AS project_id, t.id_ AS task_id, t.name_ AS task_name,
       tm.user_id_ AS user_id, tm.type_ AS member_type,
       MAX(tm.user_name_) AS user_name, COUNT(DISTINCT tm.user_name_) AS name_variants
FROM t_hpm_project_task t
JOIN t_hpm_project_task_member tm ON tm.tenant_id_ = :tenant_id
  AND tm.tenant_id_ = t.tenant_id_ AND tm.project_id_ = t.project_id_ AND tm.task_id_ = t.id_
WHERE t.tenant_id_ = :tenant_id AND t.delete_flag_ = '0' AND t.high_flag_ = '1'
  AND t.stage_id_ IS NOT NULL
  AND (:project_id IS NULL OR t.project_id_ = :project_id)
  AND (:year IS NULL OR EXISTS (
    SELECT 1 FROM t_hpm_project_stage s
    WHERE s.tenant_id_ = :tenant_id AND s.tenant_id_ = t.tenant_id_
      AND s.project_id_ = t.project_id_ AND s.id_ = t.stage_id_
      AND s.delete_flag_ = '0' AND s.name_ = :year
  )) AND tm.delete_flag_ = '0'
  AND (:task_id IS NULL OR t.id_ = :task_id)
  AND (:member_type IS NULL OR tm.type_ = :member_type)
GROUP BY t.project_id_, t.id_, t.name_, tm.user_id_, tm.type_
ORDER BY t.project_id_, t.id_, tm.user_id_, tm.type_
