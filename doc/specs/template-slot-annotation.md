# 模板逐段规则与位置提示

预制模板按语义理解、证据和当前DOCX结构编辑；旧地图用于参考，不作为写作完成合同。实现见[模板计划](template-batch-data-plan.md)与[ADR-026](../ADR/026-hybrid-template-editing.md)。

| 资产 | 职责 |
| --- | --- |
| writing-guide.md | 按段落组织主题、指标引用、特殊口径和必查项；Agent据此决定内容与取证需求 |
| document-map.json | 可选的程序生成地图，记录历史位置ID、原文、表格关系及分类建议 |
| report-data-plan.json | 可选的推荐指标和参数绑定；可以只执行选中数据集 |
| 主题指标YAML | 集中维护业务含义、参数、粒度、输出和已验证SQL；模板只引用 |

template.json登记资产、能力、数据角色、报告参数和输出策略。DOCX的登记哈希是维护基线，运行时冻结实际文件哈希；同Run源文件变化仍拒绝。

## 位置与编辑

- 当前DOCX扫描产生Run内location_hints，涵盖未标注及空段落。提示包含原文、当前标题路径、样式和物理表格行列；不把OOXML路径暴露给Agent。
- 地图原位置与原文仍吻合时沿用建议；失配后仅关联唯一原文，重复或无法确定的标注不套用。缺失或损坏地图告警，不能妨碍读取当前文档。
- 地图location_id、required、validation、scope_role和fill属于历史建议，不是授权或必填门禁，也不自动执行fill。来源范围以Run的服务端绑定为准，章节与事实的业务对应仍须按指南核查。
- 草稿target使用location_hint，或section+original_text，或table_id/row/column/paragraph。必须唯一命中当前段落；section是实际标题，section_key只用于工具分页分组。
- 表格按物理单元格编号，合并关系另行提示；不要推测视觉列号。允许填空段及未标注段落；不能通过此工具增删表格行列。
- text中的空行允许拆分普通段落，新增段落继承样式；包含字段、链接、图片等复杂内容时拒绝拆分。所有编辑先定位，再写入，避免前面的插入影响后面的目标。

## 核验边界

地图建议的未处理数量只作提醒。工具检查实际修改清单、证据范围、数字、黄字和显式残留占位符；未声明的内容、样式及其他ZIP部件不得变化。Agent仍须核查授权章节是否写完、保留的例数是否有证据，不能将程序通过当作业务审核通过。

上传模板不生成document-map，DOCX检查工具返回标题、表格、样式的语义结构；共同Skill要求参考生成新稿、重建目录并核对规范，不承诺原位编辑。

在python目录运行`python -m workflows.writing_docx.document_map --template-dir ../.claude/workflows/writing-docx/templates/szpt-midterm --check`核对地图；去掉--check重新生成。只保留可以匹配的标注和ID，新内容标为unclassified，不自动创造业务口径。

| 要求 | 状态 | 依据与差距 |
| --- | --- | --- |
| REQ-001 | 不适用 | 不改业务Token及MCP注入，既有生产验收差距保留 |
| REQ-002 | 部分满足 | 模板及提示是同一能力内部资产，外部字段不变；真实Java授权未验收 |
