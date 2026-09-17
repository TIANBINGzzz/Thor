# 模板逐段规则与位置参考

运行机制见[模板撰写](template-batch-data-plan.md)与[ADR-027](../ADR/027-agent-led-document-writing.md)。

| 资产 | 职责 |
| --- | --- |
| writing-guide.md | 丰富的模板业务上下文：主题、来源指标、特殊口径、必查项及确认边界 |
| document-map.json | 可选历史位置、原文、表格关系及分类建议，供维护核对 |
| report-data-plan.json | 可选历史取数建议，不决定运行时查询步骤 |
| 主题指标YAML | 集中维护定义、参数、粒度、输出和已验证SQL；指南仅引用 |

位置地图不作为运行依赖或必填合同，不自动填数、不按旧原文哈希拒绝撰写。Agent读取本轮实际DOCX结构后通过通用工具处理，不需要提交slot_key或target。定位、完整性与事实核验由Agent选择适合当前文档的方法，不能把原文例数当证据。

上传模板不生成地图；按其结构、样式及文稿规范生成新稿，目录按最终内容重建。预制模板也使用同一组通用工具，原DOCX保留为参考副本。

维护时可在python目录执行：
`python -m workflows.writing_docx.document_map --template-dir ../.claude/workflows/writing-docx/templates/szpt-midterm --check`
去掉--check可重新生成。仅保留能匹配的标注，新内容标为unclassified，不创造业务定义。地图失配不要求为运行而重新标注。

| 要求 | 状态 | 依据与差距 |
| --- | --- | --- |
| REQ-001 | 不适用 | 不改Token及MCP注入 |
| REQ-002 | 部分满足 | 模板为同能力内部资产，外部字段不变；Java及完整文稿未端到端验收 |
