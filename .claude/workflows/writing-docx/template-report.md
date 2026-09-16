# 固定模板撰写流程

本轮已由服务端锁定所选模板，共同写作规则与该模板说明已注入。使用data/reports完成本流程；无需再次调用Skill、Workflow或子代理。

1. 无参数调用 `get_report_data`，读取原模板章节、参数 Schema、来源角色和范围角色。提取用户指定年度、截止日及业务项目；不猜测模板缺少的业务条件。
2. 调用 `list_data_sources`、`describe_data_source` 了解获准来源和业务规则，再用 `resolve_entities` 将名称解析为 `scope_ref`。模板限定来源不可由模型更换。
3. 调用 `prepare_report_data` 绑定、去重并批量取数；用 `get_report_data` 查看完成状态，按章节分页读取全部可写位置和事实。完整数据通过 `read_query_result` 读取。
4. 按共同证据规则及所选模板说明撰写正文与可写单元格，用 `save_report_sections` 分批保存。每项包含section_key、slot_key、text、evidence_refs和evidence_state。
5. supported须有有效事实；limited同时提供gap；none正文段同时提供analysis_basis、gap、next_action。先写text，再从text逐字摘取这些字段；不改写成同义句，无证据可用空引用数组。有缺口时不得标supported；按校验错误修订原段。渲染器按状态设置黄色字体，单元格也可用同一工具覆盖初始缺口说明。
6. 全部正文完成后调用 `render_report` 原位置回填。保留全部章节、表格、图片、分节及样式；空 `section_drafts` 仅使用已保存正文，不能跳过撰写。
7. `validate_report` 完成数据完整性、原模板结构/样式对照及全文渲染；逐页 `read_report_pages` 查看排版并用 `review_report_pages` 记录实际检查。
8. 全部检查通过才 `publish_report`。修改正文后须重新回填、核验及审阅；文件生成不等于发布成功。

普通动态 SQL 可用于核实或补充调查，不能替换固定模板指标绑定、扩大来源/范围或绕过发布核验。不得读取数据库连接文件或执行模板维护脚本。
