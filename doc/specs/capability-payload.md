# 能力 payload 映射记录

现状核对：2026-09-16。templateKey解析与报告工具已接入Python；普通会话可以省略capabilityRef。下文单列尚未实现的统一模板方案，HTTP现行行为见[Runtime协议](ccsdk-runtime-interface.md#34-业务-payload)。

## 能力映射

按外层 `capabilityRef` 解释 `payload`，不在 `payload` 中重复传能力或工作流名称。

| 能力 `capabilityRef` | 场景 | 约定的 `payload` | 处理与实现状态 |
| --- | --- | --- | --- |
| `conversation` | 通用对话 | 不要求专属字段，省略或 `{}` | 问题放 `input.text`；能力路由已实现 |
| `national-excellence-data-qa` | 双高问数 | 不要求专属字段，省略或 `{}` | 问题、年份等放 `input.text`；内部映射 `database-qa` 已实现 |
| `document-writing` | 通用撰写、修改授权附件 | 省略或 `{}` | 要求放 `input.text`，外部文件用 `input.attachmentRefs`；内部映射 `writing-docx` 已实现 |
| `document-writing` | 用户上传自定义模板，保存在 Java | 省略或 `{}`，不传 `templateKey` | 模板用 `input.attachmentRefs` 引用；在 `input.text` 明确模板文件及要求，走普通撰写分支 |
| `document-writing` | 使用Python预制模板 | `{"templateKey":"szpt-midterm"}` | 锁定原40表DOCX，批量取数、逐段正文、原位回填及全文检查后发布 |

这里只登记能力约定字段；当前 Runtime 仍接受通过通用 JSON 检查的其他业务数据，尚未按此表限制字段。后续新增能力或专属字段时，在此补充类型、必填条件、用途和实现状态，不把未登记的模型输入当成已实现的服务端参数。

## 预制模板字段

| 字段 | 类型与必填条件 | 含义 |
| --- | --- | --- |
| `payload.templateKey` | 非空字符串；使用预制模板时必填 | 命中 Python 已登记、当前能力允许使用的模板标识；它不是文件路径或数据库名 |

- 选择预制模板时，`payload` 只需 `templateKey`；不要求 Java 传模板文件、模板版本、文件路径、数据源或 `reportYear`。报告年份、截止时间、主题及其他撰写要求由 `input.text` 表达，缺少必要期间时询问。
- `capabilityRef`、`runId`、`messageId` 等通用请求字段仍按 Runtime 协议传递；“只传 templateKey”指模板相关的 `payload` 字段。
- Java 维护用户可用模板及业务授权；Python 维护 `templateKey -> 本地模板 + 元数据 + 数据源引用 + 取数规则` 的可信映射。模板文件和配置版本由 Python 部署维护，执行时记录实际采用的版本，不增加客户端版本参数。
- 接入时由 Python 代码在模型执行前校验并解析 `templateKey`；只允许选择已登记且获准的资源，不能覆盖 Workflow、MCP、路径或权限。未知、空值、停用或未授权的标识应拒绝，不让模型猜模板；其他能力不解释该字段为模板选择。
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

模板query-bindings.json以source_key+domain+query_id引用[数据库资产](../../.claude/databases/README.md)，当前唯一来源schoolDoubleHigh；[可信DataContext及静态策略](data-source-connections.md)由服务端装配，路径/DSN/密码/权限不加入payload。[批量计划](template-batch-data-plan.md)记录实际工具字段及剩余差距。

2026-09-15补充：自定义模板由Java保存并授权，Python通过File Broker获取本次文件后读取结构，按需取数、组织正文并生成新DOCX；不自动注册为Python预制模板，也不要求预先配置逐格查询。当前`purpose`仅支持`input`/`reference`，模板用`input`并在正文说明用途；再次使用须重新提交附件引用。上传不授予数据源权限，数据库工具仅在已配置且获准时可用。若同时传`templateKey`和附件，仍走已登记模板分支，附件不会替换该模板。附件传递和普通撰写已有实现，复杂自定义模板保真及取数质量尚未端到端验收。

2026-09-16产品确认：两类模板均关联可用数据源；预处理模板复用已核验来源，上传模板由Agent规划取数并沿原样仿写，无须预先标槽或配置逐段SQL。自定义模板来源关联尚待接入，现有附件请求不代表按模板限定来源已实现；见[产品规则](conversation-reporting-product.md#两类模板与数据源)。

## 统一模板撰写方案（提议，未实现）

两类模板共用`document-writing → writing-docx → writing-documents`，保留现行agent-run/v1外层。以下是Java完成模板及数据源授权后发给Python的业务字段片段，不是浏览器可自由指定的执行配置。

| 字段 | 条件及含义 |
| --- | --- |
| `payload.templateKey` | 预处理模板使用现有字段；Python解析原文件、来源、可选撰写指南及绑定 |
| `payload.templateFileId` | 上传模板必填的非空文件引用；必须唯一匹配本次`attachmentRefs`中purpose=input的授权DOCX |
| `payload.dataSourceKeys` | 上传模板必填的去重来源引用数组，由Java从已保存的模板关联解析；不是连接或授权声明 |

预处理模板：`{"capabilityRef":"document-writing","input":{"text":"按深职大中期模板撰写2025年度报告"},"payload":{"templateKey":"szpt-midterm"}}`。

上传模板（拟议）：

```json
{
  "capabilityRef": "document-writing",
  "input": {
    "text": "按上传模板撰写2025年度专业群建设总结",
    "attachmentRefs": [{"fileId": "file_template_01", "purpose": "input"}]
  },
  "payload": {"templateFileId": "file_template_01", "dataSourceKeys": ["schoolDoubleHigh"]}
}
```

- `templateKey`与`templateFileId`互斥；预处理模板来源只从可信模板配置读取，拒绝请求覆盖。两者均不传时保留普通撰写/成稿修改；普通附件不自动升级为模板。
- 上传模板必须显式传来源列表；`[]`仅用于明确选择纯材料写作，省略不能默认加载能力的全部数据库。未知、不可用或越权来源整体拒绝，不能静默忽略或扩大；上传内容不能改变来源、权限或系统规则。
- 前端共用一个模板选择器，只提交获准业务模板/文件选择；Java校验归属与模板关联后生成以上字段。Python再次校验能力、来源及项目策略，只给本Run装配模板关联且获准的来源；引用不授予权限。连接、Token及SQL均不从payload接入。
- 年份、截止日、报告对象和要求继续放`input.text`，Agent在取数前解析并确认歧义；不新增重复身份、版本或Skill/Workflow选择字段。后续Run显式携带模板选择，Java重新解析当前关联与权限。

### 内部流程与目录

- 在现有`python/workflows/writing_docx/`增加请求解析模块，统一得到模板文件、有效来源、可选指南和绑定；Runtime负责调用与装配，不继续在server.py堆模板类型判断。模板解析不以数据库服务是否启用为前提。
- 保留`.claude/skills/writing-documents/SKILL.md`为共同写作入口，由可信Workflow确定性注入共同规则。现有双高Skill中的通用证据规则合入该入口，业务专属内容移到既有模板目录中的简洁writing-guide.md；数据库口径仍留semantics/，不按模板类别新建Skill。
- `.claude/workflows/writing-docx/templates/szpt-midterm/`继续保存原DOCX、元数据及现有绑定；指南和绑定是可选增强。上传模板保存在Java，通过File Broker按Run读取并生成临时段落/表格编辑计划，不自动写入预制模板目录；原逐页来源MD保留。
- 两路均先理解结构及数据需求，检索`.claude/databases/`共享指标，执行查询，检查证据后沿模板撰写；预处理来源可直接复用。指标未覆盖时仅在现有策略允许下探索只读SQL，不把临时查询自动登记为已核验指标。
- 共用证据、黄色缺口、结构保真、全文渲染和发布检查；有证据写结论，证据不足写有限结论及缺口，无证据写框架、数据需求和后续动作。复用reports校验逻辑，上传模板也需程序门禁；只合并Skill不能替代实现。
- 每Run固定模板内容哈希、指南/绑定及来源策略版本；Client指纹包含这些实际配置。模板或来源变化时隔离SDK执行上下文，业务会话保留；旧scope_ref/result_ref不跨Run复用。

当前共同能力映射、文件引用及数据授权已有基础，但上传模板两个新字段、模板范围收窄、共同Skill装配和共同发布检查均未按本方案实施；通用payload接受JSON不代表实现了字段语义。先完成请求与来源解析，再收拢Skill，最后复用编辑/校验并以两类模板做真实取数和DOCX回归，见[ADR-025](../ADR/025-unified-template-writing.md)。

## 工程要求检查

| 要求 | 状态 | 依据 | 差距与后续处理 |
| --- | --- | --- | --- |
| REQ-001 | 部分满足 | data/reports不接业务Token，原business选择性注入保留 | 真实Java撤销及日志全链路待验收 |
| REQ-002 | 部分满足 | 现有能力映射保留；拟议方案只传业务资源引用，两类模板复用Workflow与Skill | 新字段、模板来源收窄、统一校验及外部Java/前端待实施；本次仅设计 |
