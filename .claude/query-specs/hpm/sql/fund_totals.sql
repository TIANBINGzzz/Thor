WITH amounts AS (
  SELECT COUNT(*) AS fund_count,
       SUM(f.budget_total_money_) AS budget_amount,
       COUNT(f.budget_total_money_) AS budget_observed_count,
       SUM(f.investment_total_money_) AS investment_amount,
       COUNT(f.investment_total_money_) AS investment_observed_count,
       SUM(f.execute_total_money_) AS execute_amount,
       COUNT(f.execute_total_money_) AS execute_observed_count,
       SUM(f.arrival_total_money_) AS arrival_amount,
       COUNT(f.arrival_total_money_) AS arrival_observed_count

  FROM t_hpm_project_fund f
JOIN t_hpm_project p ON p.tenant_id_ = f.tenant_id_ AND p.id_ = f.project_id_
WHERE f.tenant_id_ = :tenant_id AND f.delete_flag_ = '0'
  AND p.tenant_id_ = :tenant_id AND p.delete_flag_ = '0' AND p.high_flag_ = '1'
  AND (:project_id IS NULL OR f.project_id_ = :project_id) AND f.level_ = 1 AND f.stage_id_ IS NOT NULL AND (:year IS NULL OR EXISTS (
    SELECT 1 FROM t_hpm_project_stage s
    WHERE s.tenant_id_ = :tenant_id AND s.tenant_id_ = f.tenant_id_
      AND s.project_id_ = f.project_id_ AND s.id_ = f.stage_id_
      AND s.delete_flag_ = '0' AND s.name_ = :year
  ))
)
SELECT fund_count,
       budget_amount,
       budget_observed_count,
       investment_amount,
       investment_observed_count,
       execute_amount,
       execute_observed_count,
       arrival_amount,
       arrival_observed_count,
       CASE WHEN budget_observed_count = fund_count AND execute_observed_count = fund_count
         THEN ROUND(100.0 * execute_amount / NULLIF(budget_amount, 0), 2) END AS budget_execution_rate,
       CASE WHEN budget_observed_count = fund_count AND arrival_observed_count = fund_count
         THEN ROUND(100.0 * arrival_amount / NULLIF(budget_amount, 0), 2) END AS arrival_rate,
       CASE WHEN arrival_observed_count = fund_count AND execute_observed_count = fund_count
         THEN ROUND(100.0 * execute_amount / NULLIF(arrival_amount, 0), 2) END AS arrival_execution_rate
FROM amounts
