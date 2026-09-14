WITH org_task AS (
  SELECT o.main_org_id_ AS department_id, MAX(o.main_org_name_) AS department_name,
         COUNT(DISTINCT o.main_org_name_) AS name_variants,
         t.project_id_, t.id_, t.progress_
  FROM t_hpm_project_task t
  JOIN t_hpm_project_task_org o ON o.tenant_id_ = :tenant_id
    AND o.tenant_id_ = t.tenant_id_ AND o.project_id_ = t.project_id_ AND o.task_id_ = t.id_
  WHERE t.tenant_id_ = :tenant_id AND t.delete_flag_ = '0' AND t.high_flag_ = '1'
  AND t.stage_id_ IS NOT NULL
  AND (:project_id IS NULL OR t.project_id_ = :project_id)
  AND (:year IS NULL OR EXISTS (
    SELECT 1 FROM t_hpm_project_stage s
    WHERE s.tenant_id_ = :tenant_id AND s.tenant_id_ = t.tenant_id_
      AND s.project_id_ = t.project_id_ AND s.id_ = t.stage_id_
      AND s.delete_flag_ = '0' AND s.name_ = :year
  )) AND (:level IS NULL OR t.level_ = :level)
    AND o.main_org_id_ IS NOT NULL AND o.main_org_id_ <> ''
    AND (:main_org_id IS NULL OR o.main_org_id_ = :main_org_id)
  GROUP BY o.main_org_id_, t.project_id_, t.id_, t.progress_
), metrics AS (
  SELECT department_id, MAX(department_name) AS department_name,
         MAX(name_variants) AS max_task_name_variants,
         COUNT(DISTINCT department_name) AS department_name_variants,
         COUNT(*) AS task_count, COUNT(CASE WHEN progress_ >= 100 THEN 1 END) AS completed_count,
         ROUND(AVG(COALESCE(progress_, 0)), 2) AS avg_progress,
         ROUND(100.0 * COUNT(CASE WHEN progress_ >= 100 THEN 1 END) / NULLIF(COUNT(*), 0), 2) AS completion_rate
  FROM org_task GROUP BY department_id
)
SELECT department_id, department_name, max_task_name_variants, department_name_variants,
       task_count, completed_count, avg_progress, completion_rate,
       RANK() OVER (ORDER BY avg_progress DESC) AS progress_rank
FROM metrics ORDER BY progress_rank, department_id
