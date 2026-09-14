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
      OR (module.stage_flag = '0' AND perf.stage_id_ IS NULL)) AND perf.level_ >= 3)
SELECT COUNT(*) AS performance_count,
       COUNT(CASE WHEN progress_ >= 100 THEN 1 END) AS reached_count,
       COUNT(CASE WHEN progress_ < 100 OR progress_ IS NULL THEN 1 END) AS not_reached_count,
       COUNT(CASE WHEN progress_ IS NULL THEN 1 END) AS missing_progress_count,
       ROUND(AVG(COALESCE(progress_, 0)), 2) AS avg_progress,
       ROUND(100.0 * COUNT(CASE WHEN progress_ >= 100 THEN 1 END) / NULLIF(COUNT(*), 0), 2) AS reached_rate FROM performance_scope
