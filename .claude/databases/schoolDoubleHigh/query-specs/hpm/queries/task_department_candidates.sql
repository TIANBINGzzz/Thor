SELECT DISTINCT o.main_org_id_ AS department_id, o.main_org_name_ AS department_name
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
  )) AND o.main_org_id_ IS NOT NULL AND o.main_org_id_ <> ''
  AND (:name_pattern IS NULL OR o.main_org_name_ LIKE :name_pattern)
ORDER BY o.main_org_name_, o.main_org_id_
