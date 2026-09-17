# 模板绑定与批量取数计划

固定模板流程：锁定原模板 → 完整章节及位置 → 绑定批量取数 → Agent正文 → 原位置回填 → 数据、结构样式及全文页面检查 → 发布。数据库字段见[数据源方案](data-source-connections.md)，界面与SDK边界见[产品流程](conversation-reporting-product.md)。

## 目录与职责

```text
.claude/workflows/writing-docx/
  workflow.json               数据访问模式及流程文档登记，无连接密码
  templates/
    szpt-midterm/             唯一启用的原40表规范化模板及来源
      template.json          模板入口、资产引用、数据角色、报告参数和输出策略
      writing-guide.md       逐段主题、指标引用、特殊口径和必查项
      document-map.json      程序生成的位置、原文定位、表格关系和校验信息
      report-data-plan.json  本模板所需指标、参数绑定和授权范围角色
python/workflows/writing_docx/
  template_assets.py         模板、指南、数据计划和位置地图加载校验
  document_map.py            DOCX位置地图生成、原文哈希及表格关系校验
  report_planner.py          参数展开、查询去重、取数、覆盖和分页
  report_values.py           确定值解析及动态位置待撰写状态
  report_renderer.py         草稿证据检查、黄色缺口及原位文字替换
  report_validator.py        OOXML/ZIP对照、全文渲染及逐页审阅状态
  render_wps.ps1             Windows WPS导出适配器
  tools.py                   reports MCP入口和成果发布，不是另一套写作Agent
python/runtime/data_services.py  装配Run数据服务及可选固定模板计划
```

专业群来自项目name_；建设章节来自当年任务树一级name_；表格中的产出/效益/满意度属于绩效分类树。来源关系见域内`semantics/business.md与relationships.md`，不能单凭模板标题/code猜关联。

## 入口和传值

浏览器选择`capabilityRef=document-writing`，仅传`payload.templateKey`，年份/截止日/项目/要求放input.text。Python从可信登记解析模板并校验能力，模型不能传本地路径或连接。普通会话省略capabilityRef，同一业务会话按消息选择能力。

| 工具 | 实际入参 | 行为 |
| --- | --- | --- |
| get_report_data | 无 | 返回当前模板、report_parameters Schema、source_roles和scope_roles |
| prepare_report_data | report_parameters, scope_refs | 启动计划，返回plan_ref/plan_version/status/coverage |
| get_report_data | plan_ref, section_key?, cursor?, writing_only? | 完整章节、每页最多50个位置、原文和事实引用；writing_only筛选待撰写段落及单元格 |
| save_report_sections | plan_ref, section_drafts | 分批保存；每段section_key、slot_key、text、evidence_refs必填，更新正文使旧核验失效 |
| render_report | plan_ref, section_drafts | 合并已存正文，核验证据并原位回填，不发布 |
| validate_report | plan_ref | 检查结构/样式及全部页面，返回validation_ref和page_count |
| read_report_pages | plan_ref, validation_ref, page_numbers | 每次最多4页图片，不暴露本地路径 |
| review_report_pages | 同上，加passed、notes | 记录实际查看页面的检查结论；不是自动视觉判定 |
| publish_report | plan_ref, validation_ref | 全文审阅通过、文件哈希一致才发布DOCX与缺值清单 |

report_parameters：`{"years":["2025"],"as_of":"2025-12-31","period_mode":"annual","timezone":"Asia/Shanghai"}`。
scope_refs：`{"hpm":{"group_a":"scope_...","group_b":"scope_..."}}`。学校独立项目未绑定，其章节和表格保留并明确数据缺口，不能将两个项目扩大为全校。
section_drafts每项指定原slot_key；保存和回填共用证据校验，每项最多1200字。render传空数组仅使用此前保存的草稿，任一必填动态位置未处理仍失败。固定值的查询无结果或NULL时也转入待撰写，不能自动补0或默认文案。
可信模板的file_name可引用`${years}`等已校验报告参数；渲染端禁止路径分隔符及非法文件名，年度不固定写死。

## 指标、逐段规则与位置地图

| 对象 | 字段 | 约束 |
| --- | --- | --- |
| Dataset | dataset_key, source_role, domain, scope_role, query_id, parameter_bindings | query_id引用主题指标YAML；来源角色查source_roles，再按源/域授权，模型不能改写绑定 |
| 参数绑定 | from=literal/report_parameter, value/key, expand?=each | 年份标量展开；任意表达式及先前数据集依赖尚不支持，遇到即blocked |
| Writing guide | 段落组、主题、来源指标、特殊口径、必查项 | 负责Agent理解和撰写；只引用指标ID，不保存SQL、连接或默认结论 |
| Document location | location_id, section_key, node_type, required, scope_role, template_text, locator, table, validation | 由DOCX生成并校验；只负责稳定定位、表格关系、结构保护和遗漏检查 |
| Deterministic fill | fill.text_template, fill.values | 只用于年度、截止日和已唯一取值的项目名；其余动态位置均须提交草稿 |
| 证据状态 | evidence_state=supported/limited/none，gap，analysis_basis，next_action | supported须有结果证据；limited须在正文写缺口；none正文须有分析框架、数据需求与后续动作，黄色标记，不留空 |
| Locator | part, path, expected_text_hash | 物理XML位置与文字哈希；文件变化须重新登记 |

原40表登记3503个位置，其中105个叙述段落、13个确定性填充；其余动态位置必须逐一提交处理结果。20个数据集引用主题指标YAML，统一复用其中的含义和已验证SQL。`document-map.json`不保存来源规则、SQL或缺值默认文案；Agent按`writing-guide.md`核对后原位写作。未指定内容沿用原模板仿写，缺值用具体黄色说明，不填斜杠、默认0或空白。完成全部位置只代表处理完整，不代表全部已有实值。

在`python/`下执行`python -m workflows.writing_docx.document_map --template-dir ../.claude/workflows/writing-docx/templates/szpt-midterm --check`核对地图可重复生成；去掉`--check`更新生成结果。保留已审定的位置ID和分类，重新计算原文和表格关系；原文漂移拒绝自动覆盖，须先审定新版本分类和定位。

## 执行及核验

1. 检查参数、角色、权限及版本；模板须preserve_structure=true、missing_policy=reject。同输入/版本复用本Run计划，变参生成新计划，旧计划不能交付。
2. 按source/domain/query/version/params/scope展开并去重，先执行QuerySpec依赖诊断；缺定义、缺参数或不支持的依赖在数据节点明确blocked，并作为撰写缺口，不能静默填默认值。
3. 同源只读一致性快照；源失败则整组结果失效，截断不能生成完整报告。当前不自动重试，无跨来源事务。
4. 原始结果物化在Run目录，模型按章节读取；不将几千项数据一次塞入Prompt。按指南补查的指标结果可用于草稿，但须完整且与该位置绑定的source/domain/scope一致；拒绝跨Run、来源、范围或截断结果。
5. Agent读取对应逐段规则，判定证据充分性，再完成每个动态位置；证据引用及新增数字由工具检查。无证据允许空引用，但叙述段必须呈现分析框架、数据需求和后续动作，表格位置须写具体缺口。检查不代替业务审核，数字出现在结果中也不证明语义或期间适用。
6. 输出再验文件哈希/位置；保留run、字体字号、段落/表格属性、40表、分节、图片、书签及其他ZIP部件。清除模板原编辑标记后，对不确定段落和单元格设置FFC000黄色字体；结构对照仅额外允许此颜色变化，其他漂移失败。
7. 全文导出PDF和页面图片，再实际逐页审阅；未读页面、未通过页面、旧validation_ref和文件变化均不能发布。Windows显式配置WPS；Linux镜像安装LibreOffice及中文字体，跨引擎仍需实际版面验收。

计划/结果保存在Run的data/report目录，不入Git；引用不跨Run/租户/用户。取消清理后台取数。当前每Run最多5份计划、500节点、600秒；扩大前须验证资源限制。

## 本次模拟

此前2025年度模拟保留原模板；2026-09-16用户更新规则：缺数据也须完成原段，评分等未知值用黄色说明，不能留空。不同建设周期任务名称变化按实际任务树取数，不据此否定来源；历史事实仍需对应证据，不借用旧奖项或未核实学校数据填表。
验证同时比对原QuerySpec结构、旧SQL结果、独立聚合和原文SQL语义；当前值一致不意味着历史事实成立。2026年反馈不能回填2025报告，平均进度也不是评分。

## 工程要求

| 要求 | 状态 | 依据与差距 |
| --- | --- | --- |
| REQ-001 | 部分满足 | reports复用本Run数据服务且不接业务Token；真实Java链路待验收 |
| REQ-002 | 部分满足 | 同一writing-docx复用模板；固定报告关闭文件/命令工具，来源参数受控；外部选择器和Java适配未改 |
