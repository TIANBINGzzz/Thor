# 能力 payload 映射记录

确认日期：2026-09-14。模板解析、按能力校验与报告工具已接入Python；普通会话可以省略capabilityRef。HTTP行为见[Runtime协议](ccsdk-runtime-interface.md#34-业务-payload)。

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

模板查询由query-bindings.json引用[数据库资产](../../.claude/databases/README.md)，SQL、连接、权限和版本均在服务端装配；不增加浏览器payload字段。

[数据库包](data-source-connections.md)已通过可信DataContext及静态策略接入，当前唯一来源schoolDoubleHigh。模板以source_key+domain+query_id引用查询，路径/DSN/密码/权限不加入payload；[批量计划](template-batch-data-plan.md)记录实际工具字段及剩余差距。

## 工程要求检查

2026-09-15补充：自定义模板由Java保存并授权，Python通过File Broker获取本次文件后读取结构，按需取数、组织正文并生成新DOCX；不自动注册为Python预制模板，也不要求预先配置逐格查询。当前`purpose`仅支持`input`/`reference`，模板用`input`并在正文说明用途；再次使用须重新提交附件引用。上传不授予数据源权限，数据库工具仅在已配置且获准时可用。若同时传`templateKey`和附件，仍走已登记模板分支，附件不会替换该模板。附件传递和普通撰写已有实现，复杂自定义模板保真及取数质量尚未端到端验收。

2026-09-16产品确认：预处理模板和老师上传的自定义模板均应关联可用数据源。前者复用已核验的逐段来源及指标规则；后者由Agent理解模板、规划数据需求、检索指标并查询，再沿原样仿写，无须上传前完成逐段SQL配置。预制模板的来源已由服务端templateKey映射；自定义模板的来源关联保存、授权解析及传递尚待接入，现有附件请求不代表已经落实按模板限定来源。此处不新增payload字段，实施时再定义可信引用契约；产品规则见[两类模板与数据源](conversation-reporting-product.md#两类模板与数据源)。

| 要求 | 状态 | 依据 | 差距与后续处理 |
| --- | --- | --- | --- |
| REQ-001 | 部分满足 | data/reports不接业务Token，原business选择性注入保留 | 真实Java撤销及日志全链路待验收 |
| REQ-002 | 部分满足 | 预制模板白名单、能力校验、可信映射及版本记录已实现，两类模板复用writing-docx | 自定义模板来源关联及外部Java授权、前端选择器待接入；本次仅补充产品规则 |
