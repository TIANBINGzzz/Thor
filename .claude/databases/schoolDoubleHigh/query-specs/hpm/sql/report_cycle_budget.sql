SELECT COUNT(*) AS fund_count, COUNT(f.budget_total_money_) AS budget_observed_count,
       ROUND(SUM(f.budget_total_money_), 2) AS cycle_budget_amount
FROM t_hpm_project_fund f
JOIN t_hpm_project p ON p.tenant_id_=f.tenant_id_ AND p.id_=f.project_id_
WHERE f.tenant_id_=:tenant_id AND f.delete_flag_='0' AND f.level_=1
  AND p.delete_flag_='0' AND p.high_flag_='1'
  AND (:project_id IS NULL OR f.project_id_=:project_id)
  AND (f.stage_id_ IS NULL OR TRIM(f.stage_id_)='')
