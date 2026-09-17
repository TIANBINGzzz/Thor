# 模板逐段规则与位置地图

预制模板将写作语义、数据指标和DOCX位置分开维护，当前实现见[模板计划](template-batch-data-plan.md)。模板资产不保存SQL、表名、连接信息或默认结论。

## 四类资产

| 资产 | 职责 |
| --- | --- |
| `writing-guide.md` | 按段落组维护主题、来源指标ID、特殊口径和必查项；指导Agent判断证据并仿照原文撰写 |
| `document-map.json` | 由程序扫描DOCX生成稳定位置ID、原文哈希、表格行列关系、节点类型和结构校验信息 |
| `report-data-plan.json` | 声明本模板要预取的指标ID、报告参数绑定和授权范围角色 |
| 主题指标YAML | 统一维护指标含义、参数、粒度、输出、校验规则和已验证SQL |

`template.json`只登记上述资产、DOCX哈希、能力、数据角色、报告参数和输出策略。不同模板增加自己的目录及少量配置，不复制Workflow或Skill。

## 位置地图

地图覆盖DOCX中的静态和动态段落。静态位置参与结构完整性校验；动态位置还参与遗漏检查。每个位置至少记录：

```json
{
  "location_id": "T03_R002_C05_P01",
  "section_key": "T03",
  "node_type": "scalar",
  "required": true,
  "scope_role": "school",
  "template_text": "__",
  "locator": {
    "part": "word/document.xml",
    "path": "/w:document/w:body/w:tbl[3]/w:tr[2]/w:tc[5]/w:p",
    "expected_text_hash": "..."
  },
  "table": {"table_id": "T03", "row": 2, "column": 5, "paragraph": 1},
  "validation": {"preserve_structure": true, "reject_template_default": true}
}
```

地图不维护`source_rules`、`evidence_datasets`、SQL或缺值默认文案。年度、截止日和唯一项目名等确定值可登记`fill`；其他动态位置全部交给逐段撰写流程处理。

## 执行规则

1. 加载所选模板的指南、数据计划和位置地图，校验DOCX哈希、版本、原文哈希及表格关系。
2. 按数据计划引用的主题指标执行授权查询；指标未定义或无结果时保留明确缺口。
3. Agent按指南逐段分类和取证。有证据写结论；证据不足写有限结论和缺口；完全无证据写分析框架、数据需求和后续动作。
4. 每个动态位置必须提交处理结果。表格未知项写具体缺口，正文沿用原段主题和结构；不留空、不填斜杠、不用默认0。
5. 渲染器只替换已登记段落，黄色标记不确定内容，并核对结构、样式、全部页面和遗漏状态。

## 工程要求检查

| 要求 | 状态 | 依据 | 差距 |
| --- | --- | --- | --- |
| REQ-001 | 不适用 | 本规范不改业务Token或MCP凭据传递 | 生产Token链路仍按原要求验收 |
| REQ-002 | 部分满足 | 模板、指南、指标及位置地图均为`document-writing`能力内部资产 | Java端到端授权与模板选择仍未在本仓库验收 |
