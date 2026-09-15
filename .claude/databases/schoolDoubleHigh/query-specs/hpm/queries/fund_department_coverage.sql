WITH fund_base AS (
  SELECT f.tenant_id_, f.project_id_, f.id_ AS fund_id, f.task_id_, f.execute_total_money_
  FROM t_hpm_project_fund f
  JOIN t_hpm_project p ON p.tenant_id_ = f.tenant_id_ AND p.id_ = f.project_id_
  WHERE f.tenant_id_ = :tenant_id AND f.delete_flag_ = '0'
  AND p.tenant_id_ = :tenant_id AND p.delete_flag_ = '0' AND p.high_flag_ = '1'
  AND (:project_id IS NULL OR f.project_id_ = :project_id) AND (:year IS NULL OR EXISTS (
    SELECT 1 FROM t_hpm_project_stage s
    WHERE s.tenant_id_ = :tenant_id AND s.tenant_id_ = f.tenant_id_
      AND s.project_id_ = f.project_id_ AND s.id_ = f.stage_id_
      AND s.delete_flag_ = '0' AND s.name_ = :year
  ))
), fund_task AS (
  SELECT b.tenant_id_, b.project_id_, b.fund_id, b.execute_total_money_, t.id_ AS task_id
  FROM fund_base b JOIN t_hpm_project_task t ON t.tenant_id_ = :tenant_id
    AND t.tenant_id_ = b.tenant_id_ AND t.project_id_ = b.project_id_ AND t.id_ = b.task_id_
  WHERE t.delete_flag_ = '0'
), fund_org AS (
  SELECT DISTINCT b.project_id_, b.fund_id, b.execute_total_money_, o.main_org_id_ AS department_id
  FROM fund_task b JOIN t_hpm_project_task_org o ON o.tenant_id_ = :tenant_id
    AND o.tenant_id_ = b.tenant_id_ AND o.project_id_ = b.project_id_ AND o.task_id_ = b.task_id
  WHERE o.main_org_id_ IS NOT NULL AND o.main_org_id_ <> ''
), matched_fund AS (
  SELECT DISTINCT project_id_, fund_id FROM fund_org
), org_metrics AS (
  SELECT department_id, COUNT(*) AS fund_count,
         COUNT(execute_total_money_) AS observed_count,
         COALESCE(SUM(execute_total_money_), 0) AS execute_sum
  FROM fund_org GROUP BY department_id
)
SELECT (SELECT COUNT(*) FROM fund_base) AS total_fund_count,
       (SELECT COUNT(*) FROM fund_base WHERE task_id_ IS NOT NULL) AS fund_with_task_count,
       (SELECT COUNT(*) FROM fund_task) AS matched_task_count,
       (SELECT COUNT(*) FROM matched_fund) AS matched_department_fund_count,
       ROUND(100.0 * (SELECT COUNT(*) FROM matched_fund) / NULLIF((SELECT COUNT(*) FROM fund_base), 0), 2) AS coverage_rate,
       (SELECT COUNT(*) FROM org_metrics) AS department_count,
       (SELECT COUNT(*) FROM org_metrics WHERE execute_sum = 0) AS zero_execute_department_count,
       (SELECT COUNT(*) FROM org_metrics WHERE observed_count = 0) AS all_missing_department_count,
       (SELECT COUNT(*) FROM org_metrics WHERE observed_count < fund_count) AS incomplete_department_count
