# 实体粒度

聚合前先确定主实体，不能把一对多关系表的行数当作实体数。

| 实体 | 表 | 一行代表 | 业务去重键 |
|---|---|---|---|
| Project | `t_hpm_project` | 一个项目 | `project_id` |
| Stage | `t_hpm_project_stage` | 一个项目下的一个阶段/年度 | `project_id + stage_id` |
| ProjectModule | `t_hpm_project_module` | 一个项目的模块配置 | `project_id` |
| ProjectMember | `t_hpm_project_member` | 一个项目、人员、角色关系 | `project_id + user_id + type` |
| Task | `t_hpm_project_task` | 任务树的一个节点 | `project_id + task_id` |
| TaskFeedback | `t_hpm_project_task_feedback` | 一次任务反馈提交 | `project_id + task_id + feedback_id` |
| TaskMember | `t_hpm_project_task_member` | 一个任务、人员、角色关系 | `project_id + task_id + user_id + type` |
| TaskOrg | `t_hpm_project_task_org` | 一个任务与负责主部门的关系 | `project_id + task_id + main_org_id` |
| Performance | `t_hpm_project_performance` | 绩效树的一个指标节点 | `project_id + performance_id` |
| PerformanceFeedback | `t_hpm_project_performance_feedback` | 一次绩效反馈提交 | `project_id + performance_id + feedback_id` |
| PerformanceOrg | `t_hpm_project_performance_org` | 一个绩效指标与主部门关系 | `project_id + performance_id + main_org_id` |
| Fund | `t_hpm_project_fund` | 资金树的一个节点 | `project_id + fund_id` |

同一任务可能关联多个部门，同一项目/任务/绩效可能有多条成员或反馈。使用 `COUNT(DISTINCT ...)` 或先 CTE 去重，避免 join 乘法。
