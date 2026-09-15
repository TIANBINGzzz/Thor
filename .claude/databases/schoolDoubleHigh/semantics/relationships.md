# 实体关联与去重

所有关联同时满足tenant_id_；双方有project_id_时也必须相等。不能从库中发现的租户值推导用户权限。当前单租户部署仍须使用工具解析的授权范围。

| 主实体 | 关联 | 去重粒度（均在同租户内） |
|---|---|---|
| 项目 | stage/module/member/task/performance/fund.project_id_=project.id_ | 项目主键；模块检查唯一有效配置；成员按项目+人员+角色 |
| 阶段 | task/performance/fund.stage_id_=stage.id_，同时同项目 | 项目+阶段；同年跨项目不能只取一条阶段 |
| 任务树 | child.parent_id_=parent.id_，同时同项目、阶段 | 项目+任务；一级→二级→三级，不按名称拼关系 |
| 任务反馈 | feedback.task_id_=task.id_ | 项目+任务+反馈键；反馈条数不是任务数或成果数 |
| 任务成员 | member.task_id_=task.id_ | 项目+任务+人员+角色 |
| 任务部门 | org.task_id_=task.id_ | 项目+任务+main_org_id_ |
| 任务资金 | fund.task_id_=task.id_ | 项目+资金；检查实际关联覆盖，不能猜测归属部门 |
| 任务绩效 | relation.task_id_=task.id_ AND relation.performance_id_=performance.id_ | 项目+任务+绩效；跨任务汇总按绩效键再去重 |
| 绩效树 | child.parent_id_=parent.id_；first_item_id_/second_item_id_回溯level_=1/2分类 | 项目+绩效；不通过编码猜关系 |
| 绩效反馈 | feedback.performance_id_=performance.id_ | 项目+绩效+反馈键；累计值不能跨反馈相加 |
| 绩效部门 | org.performance_id_=performance.id_ | 项目+绩效+main_org_id_ |
| 资金树 | child.parent_id_=parent.id_ | 项目+资金；金额汇总明确层级及年度 |

部门关系表和任务绩效关系表没有delete_flag_，通过有效主实体筛选。main_org_*是负责主部门，不能与人员所属部门或org_*混用。
任务performance_ids_、绩效task_ids_是JSON文本弱关联；常规统计使用真实关系表，不使用字符串匹配。
一对多关联先按上表去重或预聚合再求和、计数，避免反馈、成员和部门交叉连接放大结果。
纯任务统计按任务自身国双高标记；为展示名称关联项目时检查标记差异，不因此静默丢弃任务。项目、资金、绩效查询按有效项目国双高标记。
绩效是否按阶段由有效模块开关确定；任务绩效关系查询允许无阶段绩效，按阶段绩效则须与任务阶段一致。模块异常先处理诊断，不能把查不到当0。
