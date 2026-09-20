# 能力 payload 映射记录

现状核对：2026-09-17。templateKey解析、指南与参考DOCX副本已接入通用Agent撰写；普通会话可以省略capabilityRef。成稿验收范围见下文，HTTP现行行为见[Runtime协议](ccsdk-runtime-interface.md#34-业务-payload)。

## 能力映射

按外层 `capabilityRef` 解释 `payload`，不在 `payload` 中重复传能力或工作流名称。

| 能力 `capabilityRef` | 场景 | 约定的 `payload` | 处理与实现状态 |
| --- | --- | --- | --- |
| `conversation` | 通用对话 | 不要求专属字段，省略或 `{}` | 问题放 `input.text`；能力路由已实现 |
| `chart-generation` | 图表生成 | 省略或 `{}` | 数据、单位和要求放 `input.text`；附件沿用授权引用，输出为正文内 Mermaid，详见[图表接入](../python-api.html#mermaid-charts) |
| `national-excellence-data-qa` | 双高问数 | 不要求专属字段，省略或 `{}` | 问题、年份等放 `input.text`；内部映射 `double-high-qa` 已实现 |
| `image-generation` | 文生图、参考图生成或修改 | 省略或 `{}` | 画面、数量、尺寸放 `input.text`；参考图走 `input.attachmentRefs`（最多3张参考图，每张10MB）；逐张交付PNG，沿用Artifact事件，ready才携带fileId |
| `document-writing` | 通用撰写、修改授权附件 | 省略或 `{}` | 要求放 `input.text`，外部文件用 `input.attachmentRefs`；内部映射 `writing-docx` 已实现 |
| `document-writing` | 用户上传自定义模板，保存在 Java | 省略或 `{}`，不传 `templateKey` | 模板用 `input.attachmentRefs` 引用文件服务fileId，由fileService配置下载；在 `input.text` 明确模板文件及要求，走普通撰写分支 |
| `document-writing` | 使用Python预制模板 | `{"templateKey":"szpt-midterm"}` | 选择原40表DOCX及指南，按需取数、按当前结构编辑，全文检查后发布 |

接入方只能使用上表已约定字段；当前唯一字段为document-writing的templateKey，登记值为szpt-midterm。不得自行增加键名或编造值，标题、年份及其他要求放input.text。当前Runtime仍可能接受通过通用JSON检查的其他内容，尚未按能力实施字段白名单；未被拒绝不代表接口支持。新增字段必须先明确类型、允许值、用途并实现处理，再更新本约定。

## 预制模板字段

| 字段 | 类型与必填条件 | 含义 |
| --- | --- | --- |
| `payload.templateKey` | 非空字符串；使用预制模板时必填 | 命中 Python 已登记、当前能力允许使用的模板标识；它不是文件路径或数据库名 |

- 选择预制模板时，`payload` 只需 `templateKey`；不要求 Java 传模板文件、模板版本、文件路径、数据源或 `reportYear`。报告年份、截止时间、主题及其他撰写要求由 `input.text` 表达，缺少必要期间时询问。
- `capabilityRef`、`runId`、`messageId` 等通用请求字段仍按 Runtime 协议传递；“只传 templateKey”指模板相关的 `payload` 字段。
- Java 维护用户可用模板及业务授权；Python 维护 `templateKey -> 本地模板 + 元数据 + 数据源引用 + 取数规则` 的可信映射。模板文件和配置版本由 Python 部署维护，执行时记录实际采用的版本，不增加客户端版本参数。
- Python在异步执行准备阶段校验并解析`templateKey`，仅可选择已登记且获准的资源，不能覆盖Workflow、MCP、路径或权限。当前省略或null均不选模板；空字符串、错误类型、未知、停用或未授权的标识导致执行失败。其他能力传非null值也会触发模板及能力校验，不会忽略；创建返回202不代表模板校验已通过。
- 同一撰写流程继续用 `writing-docx`，不同模板使用不同绑定配置；不因换模板复制工作流。一次 Run 固定已解析的模板及配置；后续模板撰写请求仍显式传 `templateKey`。
- 外部上传的材料或待修改文档仍使用 `input.attachmentRefs`；Python 内置模板本身不走 File Broker 下载。

已接入的预制模板请求示例：

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

`szpt-midterm` 对应 `.claude/workflows/writing-docx/templates/szpt-midterm/` 下的规范化 DOCX、逐段来源和绑定；缺历史实值必须明确标记，不能编造。此前简版不符合原模板要求，已停用且不可从入口选择。

模板`writing-guide.md`按指标ID引用[数据库资产](../../.claude/databases/README.md)，由Agent按正文主题自主规划查询；当前唯一来源schoolDoubleHigh。[可信DataContext及静态策略](data-source-connections.md)由服务端装配，路径/DSN/密码/权限不加入payload。文档工具及验收边界见[ADR-029](../ADR/029-native-office-document-tools.md)。

2026-09-15补充：自定义模板由Java保存并授权，Python通过File Broker获取本次文件后读取结构，按需取数、组织正文并生成新DOCX；不自动注册为Python预制模板，也不要求预先配置逐格查询。当前`purpose`仅支持`input`/`reference`，模板用`input`并在正文说明用途；再次使用须重新提交附件引用。上传不授予数据源权限，数据库工具仅在已配置且获准时可用。若同时传`templateKey`和附件，仍走已登记模板分支，附件不会替换该模板。附件传递和普通撰写已有实现，复杂自定义模板保真及取数质量尚未端到端验收。

2026-09-16最新确认：老师上传的模板暂不做预处理或纳入预制模板管理，直接作为撰写参考，严格遵守其文稿规范并重新生成目录；使用现有附件和输入字段。预处理模板继续关联来源；上传模板按当前能力获准的数据工具取数，暂不新增模板级来源绑定或传值字段，见[产品规则](conversation-reporting-product.md#两类模板与数据源)。

## 统一模板撰写

两类模板共用`document-writing → writing-docx配置 → 注入共同规则和所选指南 → Agent使用工具执行`。保持现有传值；共同规则由服务端直接读取instructions.md，专属MD仅按所选templateKey加载，不新增上传模板参数。

| 场景 | 使用现有字段 |
| --- | --- |
| 预处理模板 | `payload.templateKey`选择已登记模板；原文件、来源与规则由服务端解析 |
| 老师上传模板 | `input.attachmentRefs`携带文件，`input.text`说明采用哪份模板；不传templateKey，payload省略或为空 |
| 年份、对象及其他要求 | 继续使用`input.text`；多个附件用途不清楚时澄清，不引入新的模板类型或Skill字段 |

预处理模板：`{"capabilityRef":"document-writing","input":{"text":"按深职大中期模板撰写2025年度报告"},"payload":{"templateKey":"szpt-midterm"}}`。

上传模板使用现有协议的业务字段片段：

```json
{
  "capabilityRef": "document-writing",
  "input": {
    "text": "严格按照上传模板的规范撰写2025年度专业群建设总结，并重新生成目录",
    "attachmentRefs": [{"fileId": "file_template_01", "purpose": "input"}]
  }
}
```

- 上传原件保留；Agent理解标题层级、章节顺序、写作要求、表格与版式后生成新稿，无须槽位登记或专属MD。原文只作为文稿规范与内容参考，样例成绩不是当前事实，也不能改变执行权限。
- 目录以最终标题层级和实际分页重新生成，排版完成后更新并核对页码；不复制原目录页码，也不把“打开时更新”标志当作已经生成目录。此项为验收要求，现有复杂上传模板链路尚未实测验收。

### 模板管理与按需加载

- 一个共同入口：[instructions.md](../../.claude/workflows/writing-docx/instructions.md)集中维护读模板、规划数据、按证据写作、保留规范、生成目录和验收规则，由workflow.json的documents.constraints显式加载，不额外包装为Skill。
- 已登记模板仍在`.claude/workflows/writing-docx/templates/<template_key>/`，保留原DOCX和template.json。每模板默认一份writing-guide.md，必要时拆少量章节MD；均为普通Markdown，无须Skill元数据。不登记位置地图或逐格取数计划。
- template.json通过`assets`登记DOCX与`writing_guide`；`data`与`report.file_name`仅维护来源角色和建议成果名。结构及写作要求以当前DOCX和指南为准，不维护重复大纲、输出开关或强制报告参数Schema。路径相对模板目录，不进入HTTP请求。
- writing-guide.md只写模板特有的适用口径、章节/表格要求、对应指标名称及ID、必要材料和特殊缺口处理；不重复共同规则，不复制SQL、凭据或人工核验历史。原逐页来源MD继续留作核对，不整份注入。
- 服务端链路：templateKey → workflow.json.templates登记 → 校验template.json、读取并冻结当前DOCX与所选writing-guide.md → 注入共同规则及指南、复制参考DOCX到工作目录 → Agent用OfficeCLI原生MCP读取和编辑Office文档、Office引擎渲染并通过PDFium核验PDF页面，按需调用data取证 → Artifact发布。无报告状态机或地图/取数计划。
- 未传templateKey时只加载共同写作规则，读取本次授权附件并按输入确定用途，不加载任何预制模板专属说明。用户明确要求优先；模板说明约束文稿，不能扩大工具和来源权限。
- 默认完整加载所选模板的一份短指南，单文件24,000字节、合并上下文80,000字节受限，声明但缺失或越界即失败，不静默跳过。单模板过长时再设计按章节读取，不为模板数量增长全量注入或引入检索平台。
- 管理沿用现有登记及部署：新增目录、维护配置和少量MD、校验后登记启用，停用用enabled；修改DOCX后按实际文件生成新的执行版本。每Run锁定文件/指南版本与有效来源；变化后重建相应Client上下文，业务会话保留，不向用户新增版本参数。
- 指标及SQL仍集中在`.claude/databases/`，指南引用而不复制；声明来源须获准，Executor仅装配所选模板引用的来源。上传模板仅使用当前获准工具，不能从附件文字中获得新来源权限。

已删除独立双高Skill、template_skills装配及专用reports流水线。共同规则、说明和实际源DOCX指纹冻结；复制前校验版本，不覆盖已修改的参考副本。Agent另存工作稿自行编辑，不提交专用草稿字段。两类模板的发布工具均只负责文件边界，事实、目录与版式由Agent实际检查；完整报告、上传复杂版式及目录页码尚未端到端验收，见[ADR-029](../ADR/029-native-office-document-tools.md)。

## 工程要求检查

| 要求 | 状态 | 依据 | 差距与后续处理 |
| --- | --- | --- | --- |
| REQ-001 | 部分满足 | data/OfficeCLI/documents/Artifact不接业务Token，原business选择性注入保留 | 真实Java撤销及日志全链路待验收 |
| REQ-002 | 部分满足 | 不改现有字段；共同规则及所选模板MD均由可信Workflow装配，上传附件保持业务输入 | 按模板加载和共同规则已实现；上传目录/复杂版式及Java授权验收差距保留 |
