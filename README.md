# CCSDKScribe

供 Java 开发接入的 Python Claude Agent SDK Runtime。通过 Anthropic 兼容接口连接模型，按受信 Capability 调用 Workflow、Skill、MCP 和文件工具。Java 负责业务身份、租户、授权、会话和文件，Python 负责执行及 Run 生命周期。

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
.claude/      Skills、Agents、Commands、Workflow 配置
doc/          接口规范、工程要求、ADR 和静态 API 文档
```

HTTP 入口仅保留 `/health` 和 `/internal/v1/runs...`。Java 使用 Run JWT 创建、查询、订阅事件、控制执行和下载产物；固定附件经 Java HTTPS File Broker 获取。默认监听 `127.0.0.1:4310`，`SCRIBE_PORT` 可调整端口。

测试 UI、模拟 Java 服务、测试会话和上传已迁至独立项目 `../ScribePlayground`，不再是 Runtime 的运行依赖。Node 仅用于仍需 Node 的 MCP（例如 DBHub）；需要内置 DBHub 时执行 `npm ci`。

## 当前能力

- `conversation`：普通对话
- `document-writing`：通过内部 `writing-docx` Workflow 撰写 DOCX
- `national-excellence-data-qa`：通过内部 `database-qa` Workflow 进行只读问数

前端和 Java 只提交受控 `capabilityRef`，不能提交 Workflow、Skill、模型、MCP 地址或工作目录。

## 配置与安全

模型配置写在根 `.env`；数据库专属配置写在 `.claude/workflows/database-qa/workflow.env`，该文件已被 Git 忽略。不要把密钥、真实 Token、租户值、内部 ID 或真实查询结果写入代码、文档、日志或提交。当前入口仍启用 `bypassPermissions`，只适合本地或内网验证。

## 文档入口

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
