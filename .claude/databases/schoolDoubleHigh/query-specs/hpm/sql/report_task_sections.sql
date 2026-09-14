WITH leaves AS (
  SELECT t1.project_id_, t1.id_ AS first_task_id, t3.id_ AS task_id,
         t3.progress_ AS current_progress
  FROM t_hpm_project_task t1
  JOIN t_hpm_project_task t2 ON t2.tenant_id_=t1.tenant_id_ AND t2.project_id_=t1.project_id_
    AND t2.stage_id_=t1.stage_id_ AND t2.parent_id_=t1.id_ AND t2.level_=2
    AND t2.delete_flag_='0' AND t2.high_flag_='1'
  JOIN t_hpm_project_task t3 ON t3.tenant_id_=t2.tenant_id_ AND t3.project_id_=t2.project_id_
    AND t3.stage_id_=t2.stage_id_ AND t3.parent_id_=t2.id_ AND t3.level_=3
    AND t3.delete_flag_='0' AND t3.high_flag_='1'
  WHERE t1.tenant_id_=:tenant_id AND t1.delete_flag_='0' AND t1.high_flag_='1' AND t1.level_=1
), feedback AS (
  SELECT tf.project_id_, tf.task_id_, COUNT(*) AS feedback_count
  FROM t_hpm_project_task_feedback tf
  WHERE tf.tenant_id_=:tenant_id AND tf.delete_flag_='0' AND tf.state_='1'
    AND tf.date_>=:start_date AND tf.date_<:end_date
  GROUP BY tf.project_id_, tf.task_id_
)
SELECT t1.id_ AS first_task_id, t1.code_ AS section_code, t1.name_ AS section_name,
       COUNT(l.task_id) AS task_count,
       ROUND(AVG(CASE WHEN l.task_id IS NOT NULL THEN COALESCE(l.current_progress,0) END),2) AS current_average_progress,
       COALESCE(SUM(f.feedback_count),0) AS period_feedback_count
FROM t_hpm_project_task t1
JOIN t_hpm_project_stage s ON s.tenant_id_=t1.tenant_id_ AND s.project_id_=t1.project_id_ AND s.id_=t1.stage_id_
LEFT JOIN leaves l ON l.project_id_=t1.project_id_ AND l.first_task_id=t1.id_
LEFT JOIN feedback f ON f.project_id_=l.project_id_ AND f.task_id_=l.task_id
WHERE t1.tenant_id_=:tenant_id AND t1.delete_flag_='0' AND t1.high_flag_='1' AND t1.level_=1
  AND s.delete_flag_='0' AND s.name_=:year
  AND (:project_id IS NULL OR t1.project_id_=:project_id)
GROUP BY t1.id_,t1.code_,t1.name_
ORDER BY CAST(t1.code_ AS UNSIGNED),t1.id_
