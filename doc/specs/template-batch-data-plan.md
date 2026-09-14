# 模板绑定与批量取数计划

已实现固定绑定、同源快照、物化结果及DOCX渲染，保留受控动态只读查询。数据库字段见[数据源方案](data-source-connections.md)，界面与SDK边界见[产品流程](conversation-reporting-product.md)。

## 目录与职责

```text
.claude/workflows/writing-docx/
  workflow.json               来源/模板登记，无连接密码
  templates/
    szpt-midterm/             原40表规范化模板及来源，仍有未绑定规则
      template.json          版本、DOCX哈希、能力、角色和期间Schema
      query-bindings.json    数据集、业务参数及槽位文件索引
      slots/                 原表格/正文物理定位及绑定状态
    double-high-annual/      用户批准的当前两个项目年度适配报告
      template.docx          按年度任务动态展开的表格原型
      template.json          两个项目、一个年度及截止日契约
      query-bindings.json    14个项目数据集绑定
      slots.json             标量、标题、重复表格及评分空白
      build_template.py      管理员重建模板、定位及哈希
python/reporting/
  bindings.py                权限、路径、版本、位置及重复槽位校验
  register.py                原逐段Markdown映射的结构化登记
  planner.py                 参数展开、查询去重、取数、覆盖和分页
  rendering.py               确定填值、证据检查、表格展开及OOXML
python/tools/reports.py        SDK入口和成果发布，不是另一套写作Agent
```

专业群来自项目name_；建设章节来自当年任务树一级name_；表格中的产出/效益/满意度属于绩效分类树。来源关系见域内`semantics/report-lineage.md`，不能单凭模板标题/code猜关联。

## 入口和传值

浏览器选择`capabilityRef=document-writing`，仅传`payload.templateKey`，年份/截止日/项目/要求放input.text。Python从可信登记解析模板并校验能力，模型不能传本地路径或连接。普通会话省略capabilityRef，同一业务会话按消息选择能力。

| 工具 | 实际入参 | 行为 |
| --- | --- | --- |
| get_report_data | 无 | 返回当前模板、report_parameters Schema、source_roles和scope_roles |
| prepare_report_data | report_parameters, scope_refs | 启动计划，返回plan_ref/plan_version/status/coverage |
| get_report_data | plan_ref, section_key?, cursor? | 进度、每页最多50个槽位及章节数据集引用 |
| render_report | plan_ref, section_drafts | 校验最新计划、模板与证据，渲染并发布DOCX及缺项文件 |

report_parameters：`{"years":["2025"],"as_of":"2025-12-31","period_mode":"annual","timezone":"Asia/Shanghai"}`。
scope_refs：`{"hpm":{"group_a":"scope_...","group_b":"scope_..."}}`；原中期模板另需school范围。scope来自本Run获准项目，selected项目策略不能创建全校scope。
section_drafts元素是section_key、可选slot_key、text、evidence_refs。同章节有多个正文位置时必须传slot_key；空数组仅渲染已有文字及绑定数据。

## 数据集与槽位

| 对象 | 字段 | 约束 |
| --- | --- | --- |
| Dataset | dataset_key, source_role, domain, scope_role, query_id, parameter_bindings, section_keys | 来源角色查source_roles，再按源/域授权；模型不能改写绑定 |
| 参数绑定 | from=literal/report_parameter, value/key, expand?=each | 年份标量展开；任意表达式及先前数据集依赖尚不支持，遇到即blocked |
| Scalar | slot_key, section_key, kind, required, locator, dataset_key?, field?, selector?, format? | 唯一行与公开输出字段；多行未消歧不填 |
| Report参数 | report_parameter, prefix?, suffix? | 截止日等取已校验参数 |
| Table | kind=table, dataset_key, selector?, columns, empty_text? | 定位两行原型表，保留表头、按完整结果复制行，只可绑定公开字段 |
| 空白/空值 | intentional_blank且required=false；null_text? | 评分允许空白；仅登记的空值说明可替代NULL，不能默认填0 |
| Locator | part, path, expected_text_hash | 物理XML位置与文字哈希；文件变化须重新登记 |

原40表共登记3503个位置，表示完整定位，**不代表3503项已可取数**；definition_missing仍只能输出标注草稿。年度模板用重复表格承载指标实例，数据增多不新增工具或逐指标SQL。

## 执行及核验

1. 检查参数、角色、权限及版本；同输入/版本复用本Run计划，变参生成新计划，旧计划不能交付。
2. 按source/domain/query/version/params/scope展开并去重，先执行QuerySpec依赖诊断；缺定义/参数或不支持的依赖明确blocked。
3. 同源只读一致性快照；源失败则整组结果失效，截断不能生成完整报告。当前不自动重试，无跨来源事务。
4. 原始结果物化在Run目录，模型按章节读取；不将几千项数据一次塞入Prompt。
5. 程序填确定数据格；模型正文必须引用同章节已验证证据，并检查新增数字。此检查不代替业务审核，未定义历史版本不能标为历史事实。
6. 输出再验文件哈希/位置；复制未修改ZIP部件，重复表格按原型扩展。标量保留首run样式，不保证混合格式无损；最终成果另做视觉检查。
7. reports复用Artifact发布；原模板必填缺失只交草稿，年度模板拒绝未处理的必填槽位。登记的“未填报/无记录”是明确数据状态。

计划/结果保存在Run的data/report目录，不入Git；引用不跨Run/租户/用户。取消清理后台取数。当前每Run最多5份计划、500节点、600秒；扩大前须验证资源限制。

## 本次模拟

用户指定2025年至2025-12-31，并批准按当前两个实际项目调整内容，评分留空。年度报告包含项目、一级建设指标、三级任务、资金、期内反馈、绩效关联和评价依据。原模板学校全量统计、历史成果、40张固定评分表不能借用现值填充。
验证同时比对原QuerySpec结构、旧SQL结果、独立聚合和原文SQL语义；当前值一致不意味着历史事实成立。2026年反馈不能回填2025报告，平均进度也不是评分。

## 工程要求

| 要求 | 状态 | 依据与差距 |
| --- | --- | --- |
| REQ-001 | 部分满足 | reports复用本Run数据服务且不接业务Token；真实Java链路待验收 |
| REQ-002 | 部分满足 | 同一writing-docx复用模板；固定报告关闭文件/命令工具，来源参数受控；外部选择器和Java适配未改 |
