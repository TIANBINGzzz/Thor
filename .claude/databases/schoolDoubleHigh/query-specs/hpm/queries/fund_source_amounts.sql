WITH fund_base AS (
  SELECT f.budget_total_money_,
         f.investment_total_money_,
         f.execute_total_money_,
         f.arrival_total_money_,
         f.budget_centre_money_,
         f.investment_centre_money_,
         f.execute_centre_money_,
         f.arrival_centre_money_,
         f.budget_province_money_,
         f.investment_province_money_,
         f.execute_province_money_,
         f.arrival_province_money_,
         f.budget_place_money_,
         f.investment_place_money_,
         f.execute_place_money_,
         f.arrival_place_money_,
         f.budget_organizer_money_,
         f.investment_organizer_money_,
         f.execute_organizer_money_,
         f.arrival_organizer_money_,
         f.budget_enterprise_money_,
         f.investment_enterprise_money_,
         f.execute_enterprise_money_,
         f.arrival_enterprise_money_,
         f.budget_alone_money_,
         f.investment_alone_money_,
         f.execute_alone_money_,
         f.arrival_alone_money_
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
), source_rows AS (
  SELECT 'total' AS source_kind,
         budget_total_money_ AS budget_money,
         investment_total_money_ AS investment_money,
         execute_total_money_ AS execute_money,
         arrival_total_money_ AS arrival_money
  FROM fund_base
  UNION ALL
  SELECT 'centre' AS source_kind,
         budget_centre_money_ AS budget_money,
         investment_centre_money_ AS investment_money,
         execute_centre_money_ AS execute_money,
         arrival_centre_money_ AS arrival_money
  FROM fund_base
  UNION ALL
  SELECT 'province' AS source_kind,
         budget_province_money_ AS budget_money,
         investment_province_money_ AS investment_money,
         execute_province_money_ AS execute_money,
         arrival_province_money_ AS arrival_money
  FROM fund_base
  UNION ALL
  SELECT 'place' AS source_kind,
         budget_place_money_ AS budget_money,
         investment_place_money_ AS investment_money,
         execute_place_money_ AS execute_money,
         arrival_place_money_ AS arrival_money
  FROM fund_base
  UNION ALL
  SELECT 'organizer' AS source_kind,
         budget_organizer_money_ AS budget_money,
         investment_organizer_money_ AS investment_money,
         execute_organizer_money_ AS execute_money,
         arrival_organizer_money_ AS arrival_money
  FROM fund_base
  UNION ALL
  SELECT 'enterprise' AS source_kind,
         budget_enterprise_money_ AS budget_money,
         investment_enterprise_money_ AS investment_money,
         execute_enterprise_money_ AS execute_money,
         arrival_enterprise_money_ AS arrival_money
  FROM fund_base
  UNION ALL
  SELECT 'alone' AS source_kind,
         budget_alone_money_ AS budget_money,
         investment_alone_money_ AS investment_money,
         execute_alone_money_ AS execute_money,
         arrival_alone_money_ AS arrival_money
  FROM fund_base
), amounts AS (
  SELECT source_kind, COUNT(*) AS fund_count,
       SUM(budget_money) AS budget_amount,
       COUNT(budget_money) AS budget_observed_count,
       SUM(investment_money) AS investment_amount,
       COUNT(investment_money) AS investment_observed_count,
       SUM(execute_money) AS execute_amount,
       COUNT(execute_money) AS execute_observed_count,
       SUM(arrival_money) AS arrival_amount,
       COUNT(arrival_money) AS arrival_observed_count
  FROM source_rows GROUP BY source_kind
)
SELECT source_kind, fund_count,
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
FROM amounts ORDER BY source_kind
