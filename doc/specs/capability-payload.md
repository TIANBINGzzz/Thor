# 能力 payload 映射记录

确认日期：2026-09-14。本文记录已确认的业务字段约定；本轮仅记录规范，模板解析和按能力校验尚未实现。当前 HTTP 行为以 [Runtime 协议](ccsdk-runtime-interface.md#34-业务-payload) 为准。

## 能力映射

按外层 `capabilityRef` 解释 `payload`，不在 `payload` 中重复传能力或工作流名称。

| 能力 `capabilityRef` | 场景 | 约定的 `payload` | 处理与实现状态 |
| --- | --- | --- | --- |
| `conversation` | 通用对话 | 不要求专属字段，省略或 `{}` | 问题放 `input.text`；能力路由已实现 |
| `national-excellence-data-qa` | 双高问数 | 不要求专属字段，省略或 `{}` | 问题、年份等放 `input.text`；内部映射 `database-qa` 已实现 |
| `document-writing` | 通用撰写、修改授权附件 | 省略或 `{}` | 要求放 `input.text`，外部文件用 `input.attachmentRefs`；内部映射 `writing-docx` 已实现 |
| `document-writing` | 使用 Python 预制模板 | `{"templateKey":"szpt-midterm"}` | 按模板标识加载本地 DOCX、数据源及取数映射；此解析待实现 |

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

以下为接入后的预制模板请求示例；当前代码可接收其 JSON，但尚不会根据 `templateKey` 装配模板：

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

`szpt-midterm` 对应 `.claude/workflows/writing-docx/templates/szpt-midterm/` 下的规范化 DOCX 和逐段数据来源 Markdown；这是本次确认的标识映射，运行时注册尚待实现。

该模板的查询引用已记录在同目录 `query-bindings.json`，复用[共享 QuerySpec](../../.claude/query-specs/README.md)。查询标识、SQL、数据源连接及授权上下文均由服务端装配，不增加浏览器 `payload` 字段；运行时解析仍待接入。

## 工程要求检查

| 要求 | 状态 | 依据 | 差距与后续处理 |
| --- | --- | --- | --- |
| REQ-001 | 本轮不适用 | 仅登记业务字段，不修改凭据或 MCP 注入 | 接入时仍按原规则注入本次获准的 MCP |
| REQ-002 | 部分满足 | 按业务能力解释 payload，模板标识只选择可信映射并复用 Workflow | 模板白名单、Java 授权、按能力校验及版本记录待实现 |
