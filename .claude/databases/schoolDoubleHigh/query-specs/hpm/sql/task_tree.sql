SELECT t.project_id_ AS project_id, t.stage_id_ AS stage_id, t.id_ AS task_id,
       t.parent_id_ AS parent_id, t.name_ AS task_name, t.code_ AS task_code,
       t.level_ AS task_level, t.target_value_ AS target_value,
       t.complete_value_ AS complete_value, t.progress_ AS current_progress
FROM t_hpm_project_task t WHERE t.tenant_id_ = :tenant_id AND t.delete_flag_ = '0' AND t.high_flag_ = '1'
  AND t.stage_id_ IS NOT NULL
  AND (:project_id IS NULL OR t.project_id_ = :project_id)
  AND (:year IS NULL OR EXISTS (
    SELECT 1 FROM t_hpm_project_stage s
    WHERE s.tenant_id_ = :tenant_id AND s.tenant_id_ = t.tenant_id_
      AND s.project_id_ = t.project_id_ AND s.id_ = t.stage_id_
      AND s.delete_flag_ = '0' AND s.name_ = :year
  ))
ORDER BY t.project_id_, t.stage_id_, t.level_, t.code_, t.id_
