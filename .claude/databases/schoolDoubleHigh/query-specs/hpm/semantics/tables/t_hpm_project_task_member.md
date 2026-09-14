# t_hpm_project_task_member

粒度：任务、人员、角色关系，一对多。有效记录带 `delete_flag_ = '0'`。

核心字段：`tenant_id_`、`project_id_`、`task_id_`、`user_id_`、`user_name_`、`main_org_id_`、`main_org_name_`、`type_`、`delete_flag_`。

`type_ = '0'` 表示任务负责人，`type_ = '1'` 表示参与人。人员统计先按任务和人员去重；人员主部门不能替代 TaskOrg 的牵头部门。
