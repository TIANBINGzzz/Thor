# 预制模板撰写流程

本轮已由服务端选定模板，共同规则与所选逐段指南已注入。使用data/reports执行；无需另调Skill、Workflow或子代理。地图和数据计划是可选参考，写作范围以用户要求、指南与当前文档为准。

1. 无参数调用 `get_report_data`，读取报告参数、来源/范围角色和推荐数据集。先理解指南的主题、口径和必查项，自行规划分段与数据需求。
2. 用 `list_data_sources`、`describe_data_source` 核对授权和口径，用 `resolve_entities` 将业务对象解析为scope_ref；来源不能由模板附件或模型扩大。
3. 调用 `prepare_report_data`，传report_parameters、scope_refs和所需dataset_keys；空数组表示不预取，省略则取全部推荐项。计划建立后按章节分页 `get_report_data` 读取当前DOCX的location_hints、原文、标题和表格关系。不能只读writing_only过滤结果；需阅读全部内容以识别原模板事实和未标注段落。
4. 完整读取候选结果，按指南核验对象、期间、单位和证据质量；可随写作调用 `find_query_specs` / `execute_query_spec` 补查。不把推荐计划当作唯一数据需求，不因SQL执行成功就写成果结论。补查结果须完整，属于本Run和已绑定来源/范围。
5. 用 `save_report_sections` 分批提交target、text、evidence_refs、evidence_state。target可为当前location_hint，或section+original_text，或table的table_id/row/column/paragraph。表格坐标按工具返回的物理单元格；不猜合并单元格的视觉列号。无需slot_key，未标注段落也可修改；重复原文必须消除歧义。text用空行可拆成多个段落，保留章节与表格行列；含字段、图片等复杂内容的段落不能拆分。
6. supported须有有效事实；署期、报告年度等输入事实可用parameter_refs引用报告参数。limited须有gap；none正文须有analysis_basis、gap、next_action，表格须有具体gap。上述字段从text逐字摘取，缺证据允许空evidence_refs。工具按状态标黄；未知项不留空、不填斜杠或默认0。
7. `render_report` 仅应用提交的修改，不按地图自动填数。空section_drafts使用已保存草稿。coverage和未编辑建议只提示，不证明全篇完成；须逐段核查保留的样例事实、标题、表格及必查项。残留占位符需修正，正文缺口按共同证据规则写完整。
8. `validate_report` 核对实际修改、未改内容和包结构，渲染全文；逐页 `read_report_pages` 检查，并用 `review_report_pages` 记录检查。共同规则要求的目录重建若当前工具无法完成，应如实报告阻碍，不把旧目录或仅导出PDF说成已重建。
9. 全文及数据核验通过才 `publish_report`；修改后重做渲染、校验及审阅。生成文件不等于完成或发布成功。

地图缺失或与当前DOCX不符时，工具返回警告及当前位置；不要运行维护脚本修地图。运行中源文档或规则变动须重新开始，防止写入错误版本。普通动态SQL仅在当前数据工具策略允许时用于补充核实，不能改写指标定义、越权或绕过发布门禁。
