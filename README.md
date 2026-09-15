# CCSDKScribe

供 Java 开发接入的 Python Claude Agent SDK Runtime。通过 Anthropic 兼容接口连接模型，按受信 Capability 调用 Workflow、Skill、MCP 和文件工具。Java 负责业务身份、租户、授权、会话和文件，Python 负责执行及 Run 生命周期。

当前唯一数据库为校双高数据库，标识为schoolDoubleHigh。已按库集中管理登记、语义、指标和查询，业务域为hpm；先支持单租户多来源，保留可信身份、来源策略和连接选择边界。

## 快速开始

```bash
copy .env.example .env
# 编辑 .env，填写模型配置和 CCSDK_RUNTIME_JWT_SECRET
python -m pip install -r requirements.txt
python python/server.py
```

常用命令：

```bash
npm start
npm test
```

## 目录

```text
python/       FastAPI Runtime、SDK Worker、文件 Broker 和执行工具
.claude/      Skills、Agents、Commands、Workflow、模板和databases数据库资产
deploy/       云效 ECS 容器构建、配置示例与部署脚本
doc/          接口规范、工程要求、ADR 和静态 API 文档
```

HTTP 入口仅保留 `/health` 和 `/internal/v1/runs...`。Java 使用 Run JWT 创建、查询、订阅事件、控制执行和下载产物；固定附件经 Java HTTPS File Broker 获取。默认监听 `127.0.0.1:4310`，`SCRIBE_PORT` 可调整端口。

测试UI、模拟Java服务、测试会话及上传位于独立项目 `../ScribePlayground`，不是Runtime运行依赖。Node用于SDK CLI及项目脚本，数据库查询已由进程内data MCP替代DBHub。

## 当前能力

- 普通对话：请求可省略capabilityRef，内部解析为conversation
- `document-writing`：通过内部 `writing-docx` Workflow 撰写 DOCX
- `national-excellence-data-qa`：通过内部 `database-qa` Workflow 进行只读问数

撰写模板放在 `.claude/workflows/writing-docx/templates/`。szpt-midterm锁定原40表，20数据集批量取数，Agent撰写105个正文位置并原位回填，结构样式对照和逐页审阅通过后发布。历史实值缺口单独披露；此前简版已停用。

业务字段见[能力payload映射](doc/specs/capability-payload.md)；预制模板只传payload.templateKey，年份和要求放input.text。

[共享数据库资产](.claude/databases/README.md)包含18问及报告来源的参数化查询、口径、输出字段和核验。查询JSON/同名SQL为唯一维护源，检索索引由Python生成；data工具保留模型写只读SQL能力，须可信策略及数据库账号范围同时允许。

[模板批量计划](doc/specs/template-batch-data-plan.md)、[数据库管理与工具](doc/specs/data-source-connections.md)、[前端及SDK产品流程](doc/specs/conversation-reporting-product.md)区分已实现功能和接入差距。

前端和Java按消息提交可选capabilityRef；不能提交Workflow、Skill、模型、MCP地址或工作目录。同一业务会话切换能力时，Python隔离各能力Client和工具上下文。

## 配置与安全

模型配置写在根.env；数据库包的source.json登记可用能力及private/connection.json，后者保存连接/授权并引用独立秘密文件，参见deploy/data-access.example.json。不要提交凭据、真实租户、内部ID或结果明细。固定报告和direct问数关闭内置文件/命令工具；普通Agent仍启用bypassPermissions，不构成生产多租户沙箱。

报告全文检查需要Office渲染器：Linux镜像包含LibreOffice及中文字体；Windows可配置`CCSDK_REPORT_RENDERER=wps`使用已安装WPS。无法渲染或逐页审阅未通过时禁止发布。

## 文档入口

- [云效 ECS 部署](deploy/README.md)：镜像构建、运行时密钥注入、数据卷和发布限制；尚需目标环境验收。

- [文档索引](doc/README.md)
- [架构总览](ARCHITECTURE.md)
- [Runtime 接口](doc/specs/ccsdk-runtime-interface.md)
- [Java 控制面](doc/specs/java-control-plane.md)
- [工程要求](doc/specs/engineering-requirements.md)
- [ADR 索引](doc/ADR/README.md)
- [Python API 静态文档](doc/python-api.html)

文档公网发布：运行 `powershell -ExecutionPolicy Bypass -File .\scripts\publish-docs.ps1`，自动提交 HTML 更新并同步至 [在线文档](https://cp.stringedu.com/ccsdkscribe/python-api.html)。发布与回滚说明见 [文档索引](doc/README.md#html-发布)。

## 验证

```bash
npm test
python -m compileall -q python
```

许可证：Apache-2.0。
