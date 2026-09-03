# t_hpm_project_task_feedback

粒度：一次任务反馈提交，一对多。有效记录带 `delete_flag_ = '0'`。

| 字段 | 语义 |
|---|---|
| `tenant_id_` / `project_id_` / `task_id_` | 租户、项目、任务 |
| `id_` | 反馈主键，仅内部使用 |
| `create_time_` / `date_` | 创建和反馈时间 |
| `progress_` / `complete_progress_` | 本次反馈和完成进度 |
| `state_` | `0` 提交、`1` 审核通过、`2` 驳回 |
| `attachment_` | 附件 JSON/文本 |
| `user_name_` / `main_org_name_` | 反馈人及主部门 |
| `content_` | 反馈内容，不默认输出 |

Q6 只有 `state_ = '1'` 且附件非 NULL、非空串、非 `[]` 才算合格材料；按任务使用 `NOT EXISTS` 判断缺材料。
