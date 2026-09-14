# 固定模板绑定与批量取数计划

2026-09-14。用户选择方案一并保留模型生成只读 SQL。本文为待实施设计，数据库字段/授权/工具见[数据源方案](data-source-connections.md)，现有 Run 请求不变；新增资产与工具尚不存在。

## 范围与现状

深职模板有40张表、2,710个表格单元格段落映射和793个正文段落映射；其中801个目标/完成值映射分布于405个表格行位置，不代表405个唯一指标。已有 QuerySpec 23项defined、1项blocked、8项needs_definition；报告源未绑定，工具执行和逐格绑定待接入。
模板登记时整理绑定，生成时解析期间/授权范围并编译确定性计划。程序负责取数、计算、填表及覆盖检查；Agent负责需求理解、歧义处理、补充查询和有证据的正文。无需逐格模型调用，也不为每个模板复制 Workflow。

## 请求与参数归属

| 传递位置 | 字段 / 形状 | 来源与约束 |
| --- | --- | --- |
| 浏览器 -> Java -> Python | protocol, runId, messageId, businessSessionId?, capabilityRef, input, payload | 沿用现有协议；Java验权后签发Run JWT，身份仅取其tenant/sub |
| payload | `{"templateKey":"szpt-midterm"}` | 模板专属输入仅此项；Python在模型执行前检查登记/启停/Capability/Java授权并锁定模板版本 |
| input | `{"text":"生成2025年度中期自评报告，统计截至2025年底","attachmentRefs":[]}` | 报告年度、截止日与其他要求；文件仍用File Broker授权引用，不传宿主机路径 |
| 模型 -> prepare_report_data | report_parameters:object, scope_refs:object | 模型提取业务要求；服务端按模板参数声明校验。scope_refs按source_role -> scope_role -> scope_ref组织，各库分别定位school/group，多候选先消歧 |
| report_parameters | years:string[], as_of?:date, period_mode:annual/cumulative, timezone:string | years必填非空、去重；as_of含该日，内部编译成指定时区次日不含终点；累计必须显式年份集合。学校/专业群分别定位，不允许模型新增授权 |
| 可信 RunContext | run_id, tenant, subject, capability_ref, template_key, asset_revision, grant_ref, grant_revision | Python与Java确定；工具参数中不可提交。预算周期、建设周期及评分版本由模板规则/用户要求分别解析，不统一套report_year |

示例请求体：`{"protocol":"agent-run/v1","runId":"run_example","messageId":"msg_example","capabilityRef":"document-writing","input":{"text":"生成2025年度中期自评报告，统计截至2025年底"},"payload":{"templateKey":"szpt-midterm"}}`。此例不包含HTTP鉴权Header，标识均为示意。
示例工具入参：`{"report_parameters":{"years":["2025"],"as_of":"2025-12-31","period_mode":"annual","timezone":"Asia/Shanghai"},"scope_refs":{"hpm":{"school":"scope_school","group_a":"scope_group_a"}}}`。scope引用须由当前Run解析取得，缺必需角色/期间时不启动计划；不把工具输入直接作为系统配置。

## 模板及绑定字段

| 对象 | 字段 / 类型 | 含义 |
| --- | --- | --- |
| Template / template.json | template_key:string, version:int, docx_file:string, docx_sha256:string, bindings_file:string, source_roles:object, scope_roles:object, parameters:object, missing_policy:enum | 路径相对模板目录并限制在内；source_roles如hpm -> report_db，scope_roles声明school/group所需类型；模板只引用业务来源 |
| BindingManifest / query-bindings.json | version:int, template_version:int, datasets:object[], slot_files:string[], source_document:string | 扩展现有绑定文件，直接替代当前仅表级规则的权威绑定；来源MD留作溯源，不在生成时全文注入；slot_files按章节组织 |
| DatasetBinding | dataset_key:string, source_role:string, scope_role:string, query_id:string, parameter_bindings:object, depends_on:string[], result_key:string[], checks:object[] | parameter_bindings仅允许literal/report_parameter/scope_resolution/prior_result四种受控引用，不能eval模板表达式；依赖需无环且输出类型匹配 |
| Slot | slot_key:string, kind:static/scalar/table/narrative/image, locator:object, required:bool, dataset_key?:string, selector?:object, field?:string, rule_ref?:string, format?:object | scalar/table必须有取值或规则来源；static/image来自模板或授权素材；narrative绑定事实及证据需求，不绑定自由SQL |
| Locator | part:string, path:string, expected_text_hash:string | OOXML包成员与相对结构位置，绑定当前模板sha256；同一合并格只写一次，校验文字指纹。版本或定位失配立即报TEMPLATE_MISMATCH |
| Selector | scope_role:string, task_path?:string[], indicator_path?:string[], business_code?:string, business_name?:string, period_ref:string | 必须在指定范围唯一匹配；编码不默认全局唯一，名称/路径冲突返回候选；真实数据库主键仅写入Run内解析结果 |
| Format | unit?:string, decimal_places?:int, percent_scale?:0_to_1/0_to_100, null_text?:string | 先校验单位/类型再转换；定性值保留文字，金额/百分比用Decimal和已登记舍入规则 |
| Rule / 共享rules.json | rule_key:string, version:int, status:enum, type:enum, inputs:object, applicable_periods:string[], unit:string, rounding:object, checks:object[] | 类型仅允许实现并验证的ratio/weighted_sum/direction_target/qualitative等；具体公式、分母零、方向、封顶与缺值策略须登记；禁止任意Python/JS表达式 |

标量槽位形状示例：`{"slot_key":"fund_budget","kind":"scalar","locator":{"part":"word/document.xml","path":"w:body/w:tbl[1]/w:tr[2]/w:tc[2]/w:p[1]","expected_text_hash":"<登记时计算>"},"required":true,"dataset_key":"funds_annual","selector":{"scope_role":"school","period_ref":"report.single_year"},"field":"budget_amount","format":{"unit":"万元","decimal_places":2}}`。位置仅示意；single_year仅在所选年度唯一时解析，不能把多年度多行填入一个标量槽位。
数据集形状示例：`{"dataset_key":"funds_annual","source_role":"hpm","scope_role":"school","query_id":"fund_totals","parameter_bindings":{"year":{"from":"report_parameter","key":"years","expand":"each"}},"depends_on":[],"result_key":["scope_ref","year"],"checks":[{"type":"complete_result"}]}`。year/scope_ref由执行端附到结果，不伪称原SQL输出列；现有查询声明的前置诊断自动补进依赖图，不能由模板省略。
同一绩效记录可被多个Slot引用：目标/完成值取同一适用反馈版本，完成率和得分分别走规则；相同记录的不同列不重复取数。重复行表允许按绑定结果键展开，但有固定业务行的表必须逐行匹配，不能删掉未匹配行或擅自增删指标。
编译后的resolved_periods登记每个period_ref的起止、年度集合、annual/cumulative模式和历史版本规则；report_parameters.period_mode仅为默认值，各列按模板声明分别取年度/累计/建设期。不得因全局选择cumulative就将所有列累计，百分比及累计反馈快照不得跨年相加。

## 编译与执行

1. 登记：解析现有40表与逐格MD，输出初始结构化绑定；程序转换位置和明确规则，业务人员只处理冲突/缺定义/新规则。检查sha256、合并格、槽位覆盖、重复写入、所有引用、规则与来源验证；批准后发布不可变版本。
2. 准备：验证templateKey、Java权限及全部必需来源，处理授权附件；Agent提取报告参数并消歧，prepare_report_data冻结参数、模板/语义/查询/规则版本及来源绑定。未授权立即失败；合法但缺数据的来源登记缺项，不改用问数源。
3. 编译：Slot -> DatasetBinding -> QuerySpec + requires_queries -> 取数节点/规则节点/填充节点；按 source+binding版本+授权指纹+query版本+参数+期间去重。仅batch声明兼容的查询合并，不能把不同粒度/累计口径的SQL随意拼成一个大JOIN。
4. 分组：同项目同期间批量取任务树、绩效目录/关系、模块开关、反馈候选和资金；然后按登记规则取适用版本、去重、计算。现有查询不支持数组时按授权scope/年份展开调用，不能伪称已支持批量IN；新增批量版本需输出键与独立数值回归。
5. 快照：一个来源组使用同一只读一致性事务并串行取全量所需数据；不同来源组可有界并行。物化完即关闭事务，撰文不占数据库连接；跨源分别记录采集时点，不承诺分布式原子快照。数据库一致性快照不等于过去年度的业务历史快照。
6. 保存：服务端将完整结果、期间/单位/版本、依赖校验和证据关系写入Run结果集；模型仅收到plan_ref、覆盖计数、缺项和按章节结果引用。分页基于同一物化结果，达到总量限制标不完整并阻止相关必需填充。
7. 成稿：程序填固定值与表格；模型只读当前章节事实/材料并提交带evidence_ref的段落。校验数值、来源、必填覆盖及材料权限后交给既有DOCX/Artifact链路；保留样式、表格、图片关系并做版面渲染检查。

计划字段：`plan_ref, plan_version, input_fingerprint, template_revision, asset_revision, binding_revisions, grant_revision, report_parameters, resolved_periods, nodes[], coverage, status`；节点字段 `node_key, kind, dependencies, source_key, scope_ref, query_id, query_version, parameters, result_ref, status, error_code, attempts`。内部身份/实值参数不进入公共事件。
状态：plan为queued/running/ready/blocked/failed/cancelled；node为pending/running/succeeded/blocked/failed/cancelled。业务缺定义记blocked；权限错误和模板版本失配失败；依赖失败阻断下游，不返回伪成功。
幂等范围是同Run的input_fingerprint，重复prepare返回原计划；修改参数创建新plan_version并使旧版不能作为本轮最终稿。取消使用现有Run取消信号；每来源组只对瞬态错误最多重试一次，重开事务时废弃该组全部旧结果及下游计算，不能混用新旧快照。默认计划上限10分钟，实际受Run剩余预算约束。

## 模型报告工具与动态查询

| 工具 | 入参 | 返回 / 边界 |
| --- | --- | --- |
| prepare_report_data | report_parameters, scope_refs | 创建并启动可信模板计划，立即返回plan_ref/status；templateKey从RunContext取，不由工具覆盖 |
| get_report_data | plan_ref, section_key?:string, cursor?:string | 计划进度、覆盖清单、章节事实/证据及缺项；不会把全部指标塞入上下文；后台任务归属Run并随取消终止 |
| render_report | plan_ref, section_drafts:object[] | 每个草稿含section_key、text、evidence_refs；校验通过后生成产物引用；数字槽位只从计划结果填，模型段落不得任意覆写其他位置 |

数据库工具仍可供Agent发现语义、查询指标和执行动态SQL；固定模板默认走prepare_report_data，不能每格调用一次模型或SQL。问数直接用同一execute_query_spec/execute_readonly_sql/read_query_result，不依赖模板。
允许动态补数的Slot须额外登记 `dynamic_policy:{enabled:true, source_role:string, definition_ref:string, output_contract:object, checks:object[]}`，允许省略固定dataset_key。拟用 `attach_report_result(plan_ref, slot_key, result_ref)` 复核动态结果的同Run/来源/范围/期间/定义及列类型，再重算下游；无可执行业务验证器不得开放动态槽位，列类型匹配不能证明任意SQL业务等价。固定绑定、规则未定义或历史依据缺失均拒绝挂接。
模型SQL通过验证也不自动写入QuerySpec目录；重复需要的新查询由维护者审查后发布。Agent选数据源限于当前能力/模板已获准集合，模板预绑定report_db不能被动态查询改成qa_db。

## 覆盖、证据与业务缺口

每个动态值Slot都记录 value_status=filled/no_data/ambiguous/definition_missing/source_unavailable/incomplete/invalid，并保留依赖结果与evidence_ref；固定文字另计static。覆盖分母为全部动态值Slot，不以已成功查询数作分母；必需与可选分别统计。
required缺项时计划blocked，按模板missing_policy只能交付明确标注缺项的草稿，不能宣布完整成稿；可选缺项按登记文案留空/高亮。no_data、NULL、0分别呈现。输出缺项清单包含slot_key、业务名称、原因及需补规则/材料，不展示内部ID。
深职首期必须补：报告源实际连接和字段授权、任务绩效关系唯一键、年度/累计反馈适用版本、正反向/定性完成率、评分办法、终期完成度、全周期预算、收入预算执行率、成果去重。current值和最新提交时间不证明历史年度；缺定义项保留blocked/needs_definition。
成绩/成果事实从授权反馈或成果服务提取，成果按登记业务键去重，不能数反馈条数；正文与附件建立证据引用，附件经File Broker取得。学校范围独立授权，不能把两个专业群求和当学校；跨库汇总需明确业务键、单位、粒度、期间及来源优先级。

## 拟议目录与接入顺序

```text
.claude/data-sources/<source_key>.json                 业务来源登记
.claude/semantics/hpm/{model.json,profiles/,rules.json} 共享语义与来源适配
.claude/query-specs/hpm/{catalog.json,metrics.json,specs/,sql/,tests/}
.claude/workflows/writing-docx/templates/szpt-midterm/
  template.json; query-bindings.json; slots/*.json; 原DOCX与来源MD
python/data_access/                                   catalog/authorization/connections/executor/sql_policy/results/manage
python/reporting/                                     bindings/planner/rendering
python/tools/data.py                                  固定数据库MCP入口
python/tools/reports.py                               报告工具注册，共用同一data MCP进程
python/tests/                                        数据权限、执行与模板计划测试
```

以上新增目录尚未创建。连接/密钥配置位于CCSDK_DATA_CONFIG及Secret指定位置；运行明细位于配置的Run工作根下data/和report/，默认随现有.scribe-runs/管理，不入Git。初期不新增指标业务数据库或分布式任务队列；结构化定义在Git中版本化，结果使用Run内文件。
实施顺序：先实现来源配置/Java Grant/统一执行与一条问数；再接报告库和代表性绩效表、资金、评分、证据正文，验证绑定计划；最后转换全40表、补覆盖与性能回归。动态SQL从已完成数据库侧隔离的来源开放，和固定查询同批回归。接入时将问数workflow内公共语义迁入共享目录并修改显式加载规则，删除sources.json中重复职责；未登记资产不注入Prompt。
验收：合成数据检查同名跨项目、年度/累计、NULL/0、正反向/定性、重复关联、缺父节点和评分；真实报告源只读对独立基准，逐Slot覆盖；多租户/越表/越行/令牌撤销/注入/超量/取消/连接轮换；全部分页不漏行、快照重试不混用、同值多处一致、模板变更拒绝错位、DOCX渲染保持40表结构。性能记录SQL次数、模型轮数、时延/内存/结果量，不预承诺查询次数。

## 工程要求检查

| 要求 | 状态 | 依据 | 差距与后续处理 |
| --- | --- | --- | --- |
| REQ-001 | 部分满足 | 同数据源方案，凭据不进入模板、工具参数、结果与日志 | MCP隔离、在途撤销和真实Java授权链路待验收 |
| REQ-002 | 部分满足 | 模板Key不变，绑定/计划/SQL内部化，复用writing-docx与共享数据工具 | 模板装配、字段校验、计划执行、审计及生产Capability授权均待实现 |
