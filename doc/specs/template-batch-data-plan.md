# 固定模板绑定与批量取数计划

2026-09-14。用户选择方案一，确认按数据库集中管理，首期支持单租户、多数据源并保留动态SQL；当前唯一数据库仍为校本数据库。本文为待实施设计，字段/工具见[数据库包方案](data-source-connections.md)及[ADR-023](../ADR/023-database-scoped-asset-packages.md)，现有Run请求不变。

## 范围与现状

深职模板有40张表、2,710个表格单元格段落映射和793个正文段落映射；801个目标/完成值映射分布于405个行位置，不代表405个唯一指标。现有QuerySpec为23项defined、1项blocked、8项needs_definition；qa_db/report_db是待统一的旧标识，模板规则在校本库逐项核验，工具与逐格绑定待接入。
模板登记时整理绑定，生成时解析期间/授权范围并编译确定性计划。程序负责取数、计算、填表及覆盖检查；Agent负责需求理解、歧义处理、补充查询和有证据的正文。无需逐格模型调用，也不为每个模板复制 Workflow。

## 请求与参数归属

| 传递位置 | 字段 / 形状 | 来源与约束 |
| --- | --- | --- |
| 浏览器 -> Java -> Python | protocol, runId, messageId, businessSessionId?, capabilityRef, input, payload | 沿用现有协议；Java验权后签发Run JWT，身份仅取其tenant/sub |
| payload | `{"templateKey":"szpt-midterm"}` | 模板专属输入仅此项；Java保留业务授权，Python在模型执行前检查登记/启停/Capability/单租户静态策略并锁定模板版本 |
| input | `{"text":"生成2025年度中期自评报告，统计截至2025年底","attachmentRefs":[]}` | 报告年度、截止日与其他要求；文件仍用File Broker授权引用，不传宿主机路径 |
| 模型 -> prepare_report_data | report_parameters:object, scope_refs:object | 模型提取业务要求，服务端按模板参数声明校验；scope_refs按source_role -> scope_role -> scope_ref组织，本期在校本库定位学校/专业群；同库不同业务范围仍须区分 |
| report_parameters | years:string[], as_of?:date, period_mode:annual/cumulative, timezone:string | years必填非空、去重；as_of含该日，内部编译成指定时区次日不含终点；累计必须显式年份集合。学校/专业群分别定位，不允许模型新增授权 |
| 可信 DataContext及模板上下文 | run_id, tenant_id, user_id, capability_ref, template_key, asset_revision, source_versions, policy_revisions | 身份来自已验JWT；数据库包版本/摘要和权限修订按source_key记录，由静态策略解析，模型不能提交。预算/建设周期和评分版本分别解析，不统一套report_year |

示例请求体：`{"protocol":"agent-run/v1","runId":"run_example","messageId":"msg_example","capabilityRef":"document-writing","input":{"text":"生成2025年度中期自评报告，统计截至2025年底"},"payload":{"templateKey":"szpt-midterm"}}`。此例不包含HTTP鉴权Header，标识均为示意。
示例工具入参：`{"report_parameters":{"years":["2025"],"as_of":"2025-12-31","period_mode":"annual","timezone":"Asia/Shanghai"},"scope_refs":{"hpm":{"school":"scope_school","group_a":"scope_group_a"}}}`。scope引用须由当前Run解析取得，缺必需角色/期间时不启动计划；不把工具输入直接作为系统配置。

## 模板及绑定字段

| 对象 | 字段 / 类型 | 含义 |
| --- | --- | --- |
| Template / template.json | template_key:string, version:int, docx_file:string, docx_sha256:string, bindings_file:string, source_roles:object, scope_roles:object, parameters:object, missing_policy:enum | 路径相对模板根；当前source_roles为hpm -> school，未来可增其他来源角色，每个角色分别授权；scope_roles声明学校/专业群类型；不引用物理连接或数据库包路径 |
| BindingManifest / query-bindings.json | version:int, template_version:int, datasets:object[], slot_files:string[], source_document:string | 扩展现有绑定文件，直接替代当前仅表级规则的权威绑定；来源MD留作溯源，不在生成时全文注入；slot_files按章节组织 |
| DatasetBinding | dataset_key:string, source_role:string, domain:string, scope_role:string, query_id:string, parameter_bindings:object, depends_on:string[], result_key:string[], checks:object[] | QueryRef为source_key+domain+query_id；参数仅允许literal/report_parameter/scope_resolution/prior_result受控引用，不eval表达式；依赖无环且类型匹配 |
| Slot | slot_key:string, kind:static/scalar/table/narrative/image, locator:object, required:bool, dataset_key?:string, selector?:object, field?:string, rule_ref?:string, format?:object | scalar/table必须有取值或规则来源；static/image来自模板或授权素材；narrative绑定事实及证据需求，不绑定自由SQL |
| Locator | part:string, path:string, expected_text_hash:string | OOXML包成员与相对结构位置，绑定当前模板sha256；同一合并格只写一次，校验文字指纹。版本或定位失配立即报TEMPLATE_MISMATCH |
| Selector | scope_role:string, task_path?:string[], indicator_path?:string[], business_code?:string, business_name?:string, period_ref:string | 必须在指定范围唯一匹配；编码不默认全局唯一，名称/路径冲突返回候选；真实数据库主键仅写入Run内解析结果 |
| Format | unit?:string, decimal_places?:int, percent_scale?:0_to_1/0_to_100, null_text?:string | 先校验单位/类型再转换；定性值保留文字，金额/百分比用Decimal和已登记舍入规则 |
| Rule / 数据库域内rules.json | rule_key:string, version:int, status:enum, type:enum, inputs:object, applicable_periods:string[], unit:string, rounding:object, checks:object[] | 以source_key+domain+rule_key定位，问数/撰写共用；仅允许已验证的ratio/weighted_sum/direction_target/qualitative等，登记分母零/方向/封顶/缺值策略；禁止任意Python/JS表达式 |

标量槽位形状示例：`{"slot_key":"fund_budget","kind":"scalar","locator":{"part":"word/document.xml","path":"w:body/w:tbl[1]/w:tr[2]/w:tc[2]/w:p[1]","expected_text_hash":"<登记时计算>"},"required":true,"dataset_key":"funds_annual","selector":{"scope_role":"school","period_ref":"report.single_year"},"field":"budget_amount","format":{"unit":"万元","decimal_places":2}}`。位置仅示意；single_year仅在所选年度唯一时解析，不能把多年度多行填入一个标量槽位。
数据集形状示例：`{"dataset_key":"funds_annual","source_role":"hpm","domain":"hpm","scope_role":"school","query_id":"fund_totals","parameter_bindings":{"year":{"from":"report_parameter","key":"years","expand":"each"}},"depends_on":[],"result_key":["scope_ref","year"],"checks":[{"type":"complete_result"}]}`。year/scope_ref由执行端附到结果，不伪称原SQL输出列；前置诊断自动补入依赖图，不能省略。
同一绩效记录可被多个Slot引用：目标/完成值取同一适用反馈版本，完成率和得分分别走规则；相同记录的不同列不重复取数。重复行表允许按绑定结果键展开，但有固定业务行的表必须逐行匹配，不能删掉未匹配行或擅自增删指标。
编译后的resolved_periods登记每个period_ref的起止、年度集合、annual/cumulative模式和历史版本规则；report_parameters.period_mode仅为默认值，各列按模板声明分别取年度/累计/建设期。不得因全局选择cumulative就将所有列累计，百分比及累计反馈快照不得跨年相加。

## 编译与执行

1. 登记：解析现有40表与逐格MD，输出初始结构化绑定；程序转换位置和明确规则，业务人员只处理冲突/缺定义/新规则。检查sha256、合并格、槽位覆盖、重复写入、所有引用、规则与来源验证；批准后发布不可变版本。
2. 准备：验证templateKey及每个来源角色的单租户静态策略，处理Java授权附件；Agent提取参数并消歧，prepare_report_data冻结模板/各数据库包/连接/权限版本。当前仅school；未来多库逐源验证，未授权即失败，缺表/口径登记缺项，不自动换库或选择同名查询。
3. 编译：Slot -> DatasetBinding -> QuerySpec + requires_queries -> 取数/规则/填充节点；按tenant+source+domain+连接版本+授权指纹+query版本+参数+期间去重。仅合并batch声明兼容的查询，不混合不同粒度或累计口径。
4. 分组：同项目同期间批量取任务树、绩效目录/关系、模块开关、反馈候选和资金；然后按登记规则取适用版本、去重、计算。现有查询不支持数组时按授权scope/年份展开调用，不能伪称已支持批量IN；新增批量版本需输出键与独立数值回归。
5. 快照：一个来源组使用同一只读一致性事务并串行取全量所需数据；不同来源组可有界并行。物化完即关闭事务，撰文不占数据库连接；跨源分别记录采集时点，不承诺分布式原子快照。数据库一致性快照不等于过去年度的业务历史快照。
6. 保存：服务端将完整结果、期间/单位/版本、依赖校验和证据关系写入Run结果集；模型仅收到plan_ref、覆盖计数、缺项和按章节结果引用。分页基于同一物化结果，达到总量限制标不完整并阻止相关必需填充。
7. 成稿：程序填固定值与表格；模型只读当前章节事实/材料并提交带evidence_ref的段落。校验数值、来源、必填覆盖及材料权限后交给既有DOCX/Artifact链路；保留样式、表格、图片关系并做版面渲染检查。

计划字段：`plan_ref, plan_version, input_fingerprint, template_revision, asset_revision, source_versions, connection_revisions, policy_revisions, report_parameters, resolved_periods, nodes[], coverage, status`；节点字段 `node_key, kind, dependencies, source_key, domain, scope_ref, query_id, query_version, parameters, result_ref, status, error_code, attempts`。来源/连接/权限版本按source_key映射，内部身份/实值参数不进入公共事件。
状态：plan为queued/running/ready/blocked/failed/cancelled；node为pending/running/succeeded/blocked/failed/cancelled。业务缺定义记blocked；权限错误和模板版本失配失败；依赖失败阻断下游，不返回伪成功。
幂等范围是同Run的input_fingerprint，重复prepare返回原计划；修改参数创建新plan_version并使旧版不能作为本轮最终稿。取消使用现有Run取消信号；每来源组只对瞬态错误最多重试一次，重开事务时废弃该组全部旧结果及下游计算，不能混用新旧快照。默认计划上限10分钟，实际受Run剩余预算约束。

## 模型报告工具与动态查询

| 工具 | 入参 | 返回 / 边界 |
| --- | --- | --- |
| prepare_report_data | report_parameters, scope_refs | 创建并启动可信模板计划，立即返回plan_ref/status；templateKey从服务端模板上下文取，不由工具覆盖 |
| get_report_data | plan_ref, section_key?:string, cursor?:string | 计划进度、覆盖清单、章节事实/证据及缺项；不会把全部指标塞入上下文；后台任务归属Run并随取消终止 |
| render_report | plan_ref, section_drafts:object[] | 每个草稿含section_key、text、evidence_refs；校验通过后生成产物引用；数字槽位只从计划结果填，模型段落不得任意覆写其他位置 |

数据库工具仍可供Agent发现语义、查询指标和执行动态SQL；固定模板默认走prepare_report_data，不能每格调用一次模型或SQL。问数直接用同一execute_query_spec/execute_readonly_sql/read_query_result，不依赖模板。
允许动态补数的Slot须额外登记 `dynamic_policy:{enabled:true, source_role:string, definition_ref:string, output_contract:object, checks:object[]}`，允许省略固定dataset_key。拟用 `attach_report_result(plan_ref, slot_key, result_ref)` 复核动态结果的同Run/来源/范围/期间/定义及列类型，再重算下游；无可执行业务验证器不得开放动态槽位，列类型匹配不能证明任意SQL业务等价。固定绑定、规则未定义或历史依据缺失均拒绝挂接。
模型SQL通过验证也不自动写入QuerySpec目录；重复需要的新查询由维护者审查后发布。当前能力/模板只使用school，未来增加数据库也只能选择获准来源；动态查询不能替换固定槽位的来源、粒度与期间。

## 覆盖、证据与业务缺口

每个动态值Slot都记录 value_status=filled/no_data/ambiguous/definition_missing/source_unavailable/incomplete/invalid，并保留依赖结果与evidence_ref；固定文字另计static。覆盖分母为全部动态值Slot，不以已成功查询数作分母；必需与可选分别统计。
required缺项时计划blocked，按模板missing_policy只能交付明确标注缺项的草稿，不能宣布完整成稿；可选缺项按登记文案留空/高亮。no_data、NULL、0分别呈现。输出缺项清单包含slot_key、业务名称、原因及需补规则/材料，不展示内部ID。
深职首期在校本库核验：模板所需表列、任务绩效关系唯一键、年度/累计反馈适用版本、正反向/定性完成率、评分办法、终期完成度、全周期预算、收入预算执行率、成果去重。current值和最新提交时间不证明历史年度；旧report_db记录的未核验项保留blocked/needs_definition，不再假定待接第二个库。
成绩/成果事实从授权反馈或成果服务提取，成果按登记业务键去重，不能数反馈条数；正文与附件建立证据引用，附件经File Broker取得。学校范围独立授权，不能把两个专业群求和当学校；跨库汇总需明确业务键、单位、粒度、期间及来源优先级。

## 拟议目录与接入顺序

```text
.claude/databases/school/source.json                  校本库登记、连接/策略引用
.claude/databases/school/query-specs/hpm/semantics/    校本库HPM字段、口径
.claude/databases/school/query-specs/hpm/              catalog/metrics/rules/coverage.json、specs/、sql/、tests/
.claude/databases/shuanggao/                          后续双高库示例，同样放source.json和query-specs/；当前不登记
.claude/workflows/writing-docx/templates/szpt-midterm/
  template.json; query-bindings.json; slots/*.json; 原DOCX与来源MD
python/data_access/                                   __main__/context/catalog/access/connections/executor/sql_policy/results
python/reporting/                                     bindings/planner/rendering
python/tools/data.py                                  依照现有SDK方式注册data MCP
python/tools/reports.py                               报告工具注册，共用data执行器/上下文
python/tests/                                        数据权限、执行与模板计划测试
```

以上新增目录尚未创建。连接/密钥配置位于CCSDK_DATA_CONFIG及Secret指定位置；运行明细位于配置的Run工作根下data/和report/，默认随现有.scribe-runs/管理，不入Git。初期不新增指标业务数据库或分布式任务队列；结构化定义在Git中版本化，结果使用Run内文件。
实施顺序：先迁入databases/school/并接来源索引、静态策略/可信Context和统一执行，验证固定/动态SQL及两份合成库同名查询；再核验校本库代表性绩效表、资金、评分、证据正文，最后覆盖40表。公共语义通过数据库域catalog显式登记加载，替换调用方后删除顶层query-specs/旧资产及工作流语义副本；未来多租户扩access/connections，现阶段不实现Grant服务。
验收：合成数据检查同名跨项目、年度/累计、NULL/0、正反向/定性、重复关联、缺父节点和评分；真实校本库只读对独立基准，逐Slot覆盖。本期验证拒绝其他租户身份、双用户/会话、现有范围边界、撤销/注入/超量/取消/连接轮换；未来另验真实多租户隔离。检查分页不漏行、快照重试不混用、同值多处一致、模板变更拒绝错位、DOCX渲染保持40表结构；记录SQL次数、模型轮数、时延/内存/结果量，不预承诺查询次数。

## 工程要求检查

| 要求 | 状态 | 依据 | 差距与后续处理 |
| --- | --- | --- | --- |
| REQ-001 | 部分满足 | 同校本库方案，凭据不进入模板、工具参数、结果与日志 | 每轮Context、凭据轮换及真实Java链路待验收 |
| REQ-002 | 部分满足 | 模板Key不变，绑定/计划/SQL内部化；单租户采用受控静态策略 | 模板/范围/计划/审计未实现；真实细粒度ACL不能由静态全库策略替代 |
