SELECT DISTINCT t.id_ AS task_id, perf.id_ AS performance_id,
       t.name_ AS task_name, perf.name_ AS performance_name,
       p1.name_ AS first_performance_name, p2.name_ AS second_performance_name,
       perf.target_value_ AS current_target_value, perf.finish_value_ AS current_finish_value
FROM t_hpm_project_task t
JOIN t_hpm_project_stage s ON s.tenant_id_=t.tenant_id_ AND s.project_id_=t.project_id_ AND s.id_=t.stage_id_
JOIN t_hpm_project p ON p.tenant_id_=t.tenant_id_ AND p.id_=t.project_id_
JOIN t_hpm_project_task_performance_relation r
  ON r.tenant_id_=t.tenant_id_ AND r.project_id_=t.project_id_ AND r.task_id_=t.id_
JOIN t_hpm_project_performance perf
  ON perf.tenant_id_=r.tenant_id_ AND perf.project_id_=r.project_id_ AND perf.id_=r.performance_id_
LEFT JOIN t_hpm_project_performance p1
  ON p1.tenant_id_=perf.tenant_id_ AND p1.project_id_=perf.project_id_ AND p1.id_=perf.first_item_id_
  AND p1.level_=1 AND p1.delete_flag_='0'
LEFT JOIN t_hpm_project_performance p2
  ON p2.tenant_id_=perf.tenant_id_ AND p2.project_id_=perf.project_id_ AND p2.id_=perf.second_item_id_
  AND p2.level_=2 AND p2.delete_flag_='0'
WHERE t.tenant_id_=:tenant_id AND t.delete_flag_='0' AND t.high_flag_='1' AND t.level_=3
  AND s.delete_flag_='0' AND s.name_=:year
  AND p.delete_flag_='0' AND p.high_flag_='1' AND perf.delete_flag_='0' AND perf.level_>=3
  AND (:project_id IS NULL OR t.project_id_=:project_id)
  AND EXISTS (SELECT 1 FROM t_hpm_project_module m
    WHERE m.tenant_id_=p.tenant_id_ AND m.project_id_=p.id_ AND m.delete_flag_='0'
      AND ((m.performance_stage_flag_='0' AND (perf.stage_id_ IS NULL OR TRIM(perf.stage_id_)=''))
        OR (m.performance_stage_flag_='1' AND perf.stage_id_=t.stage_id_)))
ORDER BY t.id_, perf.id_
