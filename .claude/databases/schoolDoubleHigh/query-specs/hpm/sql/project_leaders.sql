SELECT p.id_ AS project_id, p.name_ AS project_name, pm.user_id_ AS user_id,
       MAX(pm.user_name_) AS user_name, COUNT(DISTINCT pm.user_name_) AS name_variants
FROM t_hpm_project p
JOIN t_hpm_project_member pm ON pm.tenant_id_ = :tenant_id
  AND pm.tenant_id_ = p.tenant_id_ AND pm.project_id_ = p.id_
WHERE p.tenant_id_ = :tenant_id AND p.delete_flag_ = '0' AND p.high_flag_ = '1'
  AND (:project_id IS NULL OR p.id_ = :project_id) AND pm.delete_flag_ = '0' AND pm.type_ = '0'
GROUP BY p.id_, p.name_, pm.user_id_ ORDER BY p.id_, pm.user_id_
