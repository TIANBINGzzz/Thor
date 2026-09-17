# 模板按需取数与编辑

流程：阅读逐段指南 → 规划内容及数据 → 选择推荐查询或补查 → 按当前DOCX结构编辑 → 核验证据、实际修改和全文页面 → 发布。两类模板共用能力及Skill，见[传值规范](capability-payload.md)。

## 维护边界

| 模块/资产 | 职责 |
| --- | --- |
| template.json、writing-guide.md | 可信资产登记、数据角色、报告参数；逐段主题、来源指标和必查项 |
| document-map.json、document_map.py | 可选历史提示及维护时生成；不要求每次格式调整重建 |
| report-data-plan.json | 推荐数据集，指标含义和SQL仍在数据库主题YAML |
| template_assets.py | 授权、指南、推荐计划和当前DOCX加载；记录地图警告及实际指纹 |
| report_locations.py | 当前结构、标题、表格、建议匹配和唯一目标解析 |
| report_planner.py | 按需计划、参数展开、去重、快照、分页及Run内草稿 |
| report_renderer.py | 证据/数字校验、段落编辑及拆分、黄字、显式占位符检查 |
| report_validator.py | 修改清单与OOXML/ZIP对照、全文渲染、逐页审阅及文件哈希 |
| tools.py | reports MCP入口和成果发布；不另建写作Agent |

旧report_values.py已移除。确定值也须由Agent依据结果和输入提交草稿，地图fill只供参考，不再自动填入。

## 工具契约

| 工具 | 入参及行为 |
| --- | --- |
| get_report_data | 无参返回模板参数、角色、推荐数据集和地图警告；plan_ref返回章节/计划；section_key及cursor分页返回当前location_hints和事实，最多50项 |
| prepare_report_data | report_parameters、scope_refs、可选dataset_keys；省略取全部推荐项，空数组不预取，未知键拒绝 |
| save_report_sections | plan_ref、section_drafts；每项target、text、evidence_refs、evidence_state；更新正文使旧渲染和验收失效 |
| render_report | 合并已存和本次草稿，只应用提交修改；至少一项编辑，不要求覆盖全部地图建议；返回残留占位符及建议覆盖统计 |
| validate_report | 检查显式占位符、修改清单、未改部分和全文渲染，返回validation_ref及页数 |
| read_report_pages / review_report_pages | 每次最多四页；先读取再记录检查，须覆盖全部页面 |
| publish_report | 当前计划、文件哈希和全文审阅均通过后，发布DOCX及缺口清单 |

target可用`{"location_hint":"loc_00001"}`，也可用`{"section":"实际章节标题","original_text":"原段全文"}`，或`{"table":{"table_id":"T01","row":1,"column":2,"paragraph":1}}`。不能传旧slot_key；当前提示ID仅在该Run基线内有效。

text最多12000字符，空行拆分普通段落；保存/渲染复用同一证据校验。supported要求完整事实结果或明确parameter_refs（如署期/年度）；limited须在正文呈现gap；none正文须呈现analysis_basis、gap、next_action，表格用具体缺口。后两种标黄，不用空白、斜杠或0替代未知。

report_parameters沿用年份、as_of、period_mode、timezone；scope_refs按source_role嵌套scope_role。学校独立范围未绑定时不把两个专业群合成学校事实。来源、域和授权范围由服务端约束；补查即使不在推荐计划，也须属于本Run、已绑定source/domain/scope且结果完整。

## 执行与核验

1. 检查参数、角色、来源及当前版本；数据集选择进入计划指纹。同输入复用计划，变参生成新计划；旧计划不能发布。
2. 选中数据集按source/domain/query/version/params/scope展开去重，执行QuerySpec依赖诊断；缺定义/参数仍为blocked节点，作为写作缺口。不得静默默认值，也不因此阻止Agent按证据完成正文。
3. 同源只读一致性快照，失败则整组结果失效；结果不跨Run或身份。每Run最多5个计划、500节点、600秒，取消清理后台任务。
4. 按当前文档逐段取证、撰写；get_report_data的writing_only只是阅读筛选，不能跳过未标注或静态建议中的样例事实。SQL成功不证明材料足以支持成果结论。
5. 渲染前复核实际DOCX及规则指纹。预解析所有目标，保持表格、图片、书签、分节和其他包部件；段落拆分只复制段落及文字样式，不复制图片或书签ID。
6. coverage只提示未编辑地图建议；不声称全部必填已处理。检查显式占位符，Agent另行复核业务完整性、例数残留及证据语义。程序数字检查不能代替期间/口径核对。
7. 全文导出PDF及页面图片，实际审阅后发布。目录重建仍为共同规则要求；当前预制渲染器只导出PDF，不负责重建目录，不能声称页码已更新。复杂上传模板、目录和全篇报告仍需专项端到端验收。

计划、草稿、结果和编辑清单留在Run目录，不入Git。已有逐页来源整理及主题指标SQL不因本次结构调整改写或重新认定业务事实。

| 要求 | 状态 | 依据与差距 |
| --- | --- | --- |
| REQ-001 | 不适用 | 未更改Token及MCP凭据传递，既有真实Java链路验收差距保留 |
| REQ-002 | 部分满足 | 同一document-writing / writing-docx，位置与取数建议保持内部，HTTP字段不变；真实Java授权和复杂成稿验收仍缺 |
