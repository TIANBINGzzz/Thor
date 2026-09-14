# t_hpm_project_member

粒度：项目、人员、成员角色关系，一对多。有效记录带 `delete_flag_ = '0'`。

| 字段 | 语义 |
|---|---|
| `tenant_id_` / `project_id_` | 租户和项目 |
| `user_id_` / `user_code_` | 人员内部标识，不可输出 |
| `user_name_` | 人员姓名，仅明确询问且允许时输出 |
| `main_org_id_` / `main_org_name_` | 人员主部门，不等同任务牵头部门 |
| `type_` | `0` 项目负责人；其他值为其他角色 |
| `delete_flag_` | 逻辑删除 |

问项目负责人默认只取 `type_ = '0'`；统计人数用去重人员，不把成员行数直接当项目数。
