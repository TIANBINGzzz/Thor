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
SELECT pf.id_ AS feedback_id, perf.project_id_ AS project_id, perf.id_ AS performance_id,
       perf.name_ AS performance_name, pf.create_time_ AS submitted_at,
       pf.year_target_value_ AS year_target_value, pf.year_complete_value_ AS year_complete_value,
       pf.total_target_value_ AS total_target_value, pf.total_complete_value_ AS total_complete_value,
       pf.progress_ AS year_progress, pf.total_progress_ AS total_progress, pf.content_ AS content,
       CASE WHEN pf.attachment_ IS NOT NULL AND pf.attachment_ <> '' AND pf.attachment_ <> '[]' THEN 1 ELSE 0 END AS has_attachment
FROM performance_scope perf
JOIN t_hpm_project_performance_feedback pf ON pf.tenant_id_ = :tenant_id
  AND pf.project_id_ = perf.project_id_ AND pf.performance_id_ = perf.id_
WHERE pf.delete_flag_ = '0' AND pf.state_ = '1'
  AND (:performance_id IS NULL OR perf.id_ = :performance_id)
  AND (:start_date IS NULL OR pf.create_time_ >= :start_date)
  AND (:end_date IS NULL OR pf.create_time_ < :end_date)
ORDER BY perf.project_id_, perf.id_, pf.create_time_, pf.id_
