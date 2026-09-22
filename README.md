# ccagentsdk

供 Java 接入的 Python Claude Agent SDK Runtime，通过 Anthropic 兼容接口连接模型。Java 管理业务身份、会话、授权和文件；Python 执行能力、维护 SDK 上下文及 Run 生命周期。

## 快速开始

```powershell
Copy-Item .env.example .env
# 编辑 .env，填写模型配置和 CCSDK_RUNTIME_JWT_SECRET
python -m pip install -r requirements.txt
python python/server.py
```

也可用 `npm start` 启动，`npm test` 运行测试。默认监听 `127.0.0.1:4310`，端口由 `SCRIBE_PORT` 配置。Node 用于 SDK CLI 和项目脚本。

## 目录与入口

```text
python/       FastAPI Runtime、SDK Worker、文件获取和执行工具
.claude/      Workflow、执行规则、模板和数据库知识资产
config/       部署配置，约束见 config/README.md
deploy/       云效 ECS 容器构建、配置示例与检查
doc/          接口契约、工程要求、现行决策和核验记录
```

HTTP 提供 `/health` 及 `/internal/v1/` 下的能力目录、Run、会话执行检索、事件、观测和成果接口。业务调用经过 Java 授权与 Run JWT；完整约定见[Runtime 契约](doc/specs/ccsdk-runtime-interface.md)。

测试前端及模拟 Java 服务已移除；业务调用直接对接 Runtime HTTP/SSE 契约。

## 能力与上下文

公开能力由 `GET /internal/v1/capabilities` 返回，包括普通对话、图表生成、图像生成、文档撰写和双高问数；Java 按用户权限筛选。输入及模板字段见[能力 payload](doc/specs/capability-payload.md)。

普通对话在配置百炼工作空间Anthropic地址和模型密钥后可按需联网搜索，复用本轮模型；搜索期间显示“正在联网搜索”，回答附实际来源。其他能力不挂载搜索工具。

同一 tenant、user 和 businessSessionId 下，Python 跨能力续接 SDK 历史；工具、规则和凭据按本轮能力重新装配。省略 capabilityRef 仍表示普通对话，不恢复前端的选择值。重启恢复需持久化 RunStore 和 SDK transcript，详见[会话决策](doc/ADR/033-business-session-continuity.md)。

文稿由 Agent 依据[共同规则](.claude/workflows/writing-docx/instructions.md)、所选模板指南及授权资料自主完成，使用 OfficeCLI 编辑、LibreOffice 渲染和 PDFium 核验。撰写轮数与时限以[Workflow 配置](.claude/workflows/writing-docx/workflow.json)为准。

当前数据库为校双高 `schoolDoubleHigh`；知识和指标 SQL 维护在[数据库资产](.claude/databases/README.md)，通过进程内 data MCP 查询。

## 配置与依赖

- 模型及 JWT 配置见 [.env.example](.env.example)；数据库、文件服务配置见[配置说明](config/README.md)与[数据库管理](doc/specs/data-source-connections.md)。本版数据库 JSON 经授权进入私有仓库及镜像，修改须重建；模型/JWT 密钥不入库。
- OfficeCLI 默认从 PATH 启动，可用 `CCSDK_OFFICECLI_PATH` 指定。Linux 镜像内置渲染依赖；Windows 运行 `docker build --target document-renderer -t ccsdkscribe-renderer:local .`，自定义镜像使用 `CCSDK_RENDER_IMAGE`。复测入口为 `scripts/benchmark-document.py`。
- 可选生图使用 `CCSDK_IMAGE_BASE_URL`、`CCSDK_IMAGE_API_KEY`、`CCSDK_IMAGE_MODEL`，配置变更后重启 Runtime。
- 普通 Agent 启用 bypassPermissions，不构成生产多租户沙箱；direct 问数关闭内置文件/命令工具。授权与部署边界见[架构](ARCHITECTURE.md)及[部署说明](deploy/README.md)。

## 文档与验证

[文档地图](ARCHITECTURE.md#9-where-to-look-for-x)统一定位接口、业务规则和核验记录；[API HTML](doc/python-api.html)用于浏览接口示例，发布与回滚见[部署说明](deploy/README.md#html-文档发布)。

```powershell
npm test
python -m compileall -q python
```

许可证：Apache-2.0。
