SELECT tf.id_ AS feedback_id, t.project_id_ AS project_id, t.id_ AS task_id,
       t.name_ AS task_name, tf.date_ AS feedback_date, tf.create_time_ AS submitted_at,
       tf.content_ AS content, tf.progress_ AS progress, tf.complete_progress_ AS complete_progress,
       CASE WHEN tf.attachment_ IS NOT NULL AND tf.attachment_ <> '' AND tf.attachment_ <> '[]' THEN 1 ELSE 0 END AS has_attachment
FROM t_hpm_project_task t
JOIN t_hpm_project_task_feedback tf ON tf.tenant_id_ = :tenant_id
  AND tf.tenant_id_ = t.tenant_id_ AND tf.project_id_ = t.project_id_ AND tf.task_id_ = t.id_
WHERE t.tenant_id_ = :tenant_id AND t.delete_flag_ = '0' AND t.high_flag_ = '1'
  AND t.stage_id_ IS NOT NULL
  AND (:project_id IS NULL OR t.project_id_ = :project_id)
  AND (:year IS NULL OR EXISTS (
    SELECT 1 FROM t_hpm_project_stage s
    WHERE s.tenant_id_ = :tenant_id AND s.tenant_id_ = t.tenant_id_
      AND s.project_id_ = t.project_id_ AND s.id_ = t.stage_id_
      AND s.delete_flag_ = '0' AND s.name_ = :year
  )) AND tf.delete_flag_ = '0' AND tf.state_ = '1'
  AND (:task_id IS NULL OR t.id_ = :task_id)
  AND (:start_date IS NULL OR tf.date_ >= :start_date)
  AND (:end_date IS NULL OR tf.date_ < :end_date)
ORDER BY t.project_id_, t.id_, tf.date_, tf.id_
