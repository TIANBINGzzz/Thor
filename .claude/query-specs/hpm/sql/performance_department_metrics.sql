WITH performance_scope AS (SELECT perf.id_, perf.project_id_, perf.stage_id_, perf.parent_id_, perf.code_, perf.name_,
         perf.level_, perf.progress_, perf.target_value_, perf.finish_value_
  FROM t_hpm_project_performance perf
  JOIN t_hpm_project p ON p.tenant_id_ = perf.tenant_id_ AND p.id_ = perf.project_id_
  JOIN (
    SELECT m.tenant_id_, m.project_id_, MIN(m.performance_stage_flag_) AS stage_flag
    FROM t_hpm_project_module m
    WHERE m.tenant_id_ = :tenant_id AND m.delete_flag_ = '0'
    GROUP BY m.tenant_id_, m.project_id_
    HAVING COUNT(*) = 1 AND MIN(m.performance_stage_flag_) IN ('0', '1')
  ) module ON module.tenant_id_ = perf.tenant_id_ AND module.project_id_ = perf.project_id_
  WHERE perf.tenant_id_ = :tenant_id AND perf.delete_flag_ = '0'
    AND p.tenant_id_ = :tenant_id AND p.delete_flag_ = '0' AND p.high_flag_ = '1'
    AND (:project_id IS NULL OR perf.project_id_ = :project_id)
    AND ((module.stage_flag = '1' AND perf.stage_id_ IS NOT NULL)
      OR (module.stage_flag = '0' AND perf.stage_id_ IS NULL)) AND perf.level_ >= 3), org_performance AS (
  SELECT o.main_org_id_ AS department_id, MAX(o.main_org_name_) AS department_name,
         COUNT(DISTINCT o.main_org_name_) AS name_variants,
         perf.project_id_, perf.id_, perf.progress_
  FROM performance_scope perf
  JOIN t_hpm_project_performance_org o ON o.tenant_id_ = :tenant_id
    AND o.project_id_ = perf.project_id_ AND o.performance_id_ = perf.id_
  WHERE o.main_org_id_ IS NOT NULL AND o.main_org_id_ <> ''
    AND (:main_org_id IS NULL OR o.main_org_id_ = :main_org_id)
  GROUP BY o.main_org_id_, perf.project_id_, perf.id_, perf.progress_
)
SELECT department_id, MAX(department_name) AS department_name,
       MAX(name_variants) AS max_indicator_name_variants,
       COUNT(DISTINCT department_name) AS department_name_variants, COUNT(*) AS performance_count,
       COUNT(CASE WHEN progress_ >= 100 THEN 1 END) AS reached_count,
       COUNT(CASE WHEN progress_ < 100 OR progress_ IS NULL THEN 1 END) AS not_reached_count,
       COUNT(CASE WHEN progress_ IS NULL THEN 1 END) AS missing_progress_count,
       ROUND(AVG(COALESCE(progress_, 0)), 2) AS avg_progress,
       ROUND(100.0 * COUNT(CASE WHEN progress_ >= 100 THEN 1 END) / NULLIF(COUNT(*), 0), 2) AS reached_rate
FROM org_performance GROUP BY department_id ORDER BY department_id
