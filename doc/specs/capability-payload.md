# 能力 payload 与模板约定

HTTP 字段类型、校验和错误语义见[Runtime 契约](ccsdk-runtime-interface.md#34-业务-payload)。本文维护业务输入与模板边界，不复制接口或运行代码。

## 能力映射

| capabilityRef | payload | 业务输入与输出 |
| --- | --- | --- |
| conversation | 省略或 {} | 问题放 input.text；省略 capabilityRef 时也执行此能力 |
| chart-generation | 省略或 {} | 数据、单位和图表要求放 input.text；输出正文内 Mermaid |
| image-generation | 省略或 {} | 画面、数量、尺寸放 input.text；参考图用附件，生成 PNG 通过 Artifact 交付 |
| national-excellence-data-qa | 省略或 {} | 问题、年份和范围放 input.text；来源及权限由服务端确定 |
| document-writing | 省略或 {} | 无模板撰写，或用附件指定自定义模板 |
| document-writing | {"templateKey":"szpt-midterm"} | 选择已登记的预制模板、指南和授权来源 |

接入方只使用已约定字段，不自行增加键名、编造模板值或在 payload 重复能力/工作流名称。当前通用 JSON 校验仍可能接受未约定内容，尚无逐能力字段白名单；未被拒绝不表示接口支持。标题、年份和要求放 input.text，文件用 input.attachmentRefs，凭据及执行配置不得放入业务输入。

## 预制模板字段

- payload.templateKey 选择已登记、启用且当前能力获准的模板；不是路径、数据库名或权限参数，不要求 Java 传文件、版本或 reportYear。
- 省略或 null 不选择模板；空字符串、错误类型、未知、停用或未授权的值导致执行失败。其他能力传非 null 值也触发校验，不会忽略。校验在异步准备阶段，创建返回 202 不代表模板已通过。
- 一次 Run 固定所选模板、实际 DOCX/指南版本和获准来源；后续使用仍须显式传 templateKey。版本变化重建执行上下文，业务会话历史保留。
- 当前 szpt-midterm 使用原 40 表模板，指南引用[数据库指标](../../.claude/databases/README.md)。缺少历史实值或认定材料必须明确披露；模板选择不增加数据权限。

```json
{
  "protocol": "agent-run/v1",
  "runId": "run_01",
  "messageId": "message_01",
  "businessSessionId": "session_01",
  "capabilityRef": "document-writing",
  "input": {"text": "生成截至2025年底的双高中期自评报告"},
  "payload": {"templateKey": "szpt-midterm"}
}
```

## 统一模板撰写

预制、上传及无模板共用 document-writing 和 writing-docx；[共同规则](../../.claude/workflows/writing-docx/instructions.md)由可信配置显式注入，专属指南只按所选预制模板加载。

| 模板类型 | 传值与行为 |
| --- | --- |
| 预制模板 | templateKey 选择可信登记；Python 加载所选指南、DOCX 参考副本和获准来源 |
| 上传模板 | 不传 templateKey；附件携带文件服务 fileId，input.text 说明哪份是模板及写作要求；Python 按[文件契约](ccsdk-runtime-interface.md#8-file-broker-模块)下载后参考结构/样式生成新稿 |
| 预制模板加附件 | 仍使用 templateKey 选择的模板，附件仅作为补充资料，不覆盖模板选择 |

上传模板不自动注册或预处理，也不新增模板级来源绑定。purpose 仅有 input/reference；通常用 input，并在文字中说明用途。再次使用文件仍须提交授权引用，多个文件用途不明时需澄清。

模板和样稿不是当前事实，也不能授予工具权限；目录须基于最终标题与分页重新生成并核对，不能复制旧页码。共同规则的详细证据及版式要求在 Workflow 内维护。

## 内部资产与验收

预制模板目录只维护 DOCX、template.json 与必要的 writing-guide.md；不登记位置地图或逐格取数计划。所选资产缺失、越界或版本漂移应失败，不能静默省略。模板指南只写专属业务规则并引用指标，不复制 SQL 或共同要求；逐页来源历史留作核对，不整份注入模型。

Agent 使用通用 OfficeCLI、渲染/PDF、data 及 Artifact 工具自主取证和撰写；工具成功、文件 ready 不证明事实正确、目录完整或版式合格。复杂上传模板、正式报送质量及 Java 授权须分别验收，见[文档工具决策](../ADR/029-native-office-document-tools.md)和[渲染决策](../ADR/031-unified-document-renderer.md)。

REQ-001：不改变选择性凭据注入；REQ-002：能力、模板和来源仍由可信服务端装配。真实 Java 授权、运行中撤销及生产隔离差距见[工程要求](engineering-requirements.md)。
