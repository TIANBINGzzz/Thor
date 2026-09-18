# ccagentsdk

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
.claude/      Workflow配置、执行规则、模板和databases数据库资产
deploy/       云效 ECS 容器构建、配置示例与部署脚本
doc/          接口规范、工程要求、ADR 和静态 API 文档
```

HTTP入口包括`/health`及`/internal/v1/`下的能力目录、Run和会话执行检索。Java使用Run JWT创建、查询、订阅事件、控制执行和下载产物；固定附件经Java HTTPS File Broker获取。默认监听`127.0.0.1:4310`，`SCRIBE_PORT`可调整端口。
按业务会话检索执行记录使用`GET /internal/v1/sessions/{businessSessionId}/runs`，Java签发绑定会话及身份的`session.read` JWT，返回执行摘要和nextCursor；会话标题与消息仍由Java管理。详见[分页契约](doc/specs/ccsdk-runtime-interface.md#43-按业务会话查询执行记录)。

测试UI、模拟Java服务、测试会话及上传位于独立项目 `../ScribePlayground`，不是Runtime运行依赖。Node用于SDK CLI及项目脚本，数据库查询已由进程内data MCP替代DBHub。

## 当前能力

- 普通对话：请求可省略capabilityRef，内部解析为conversation
- `document-writing`：通过内部 `writing-docx` Workflow 撰写 DOCX
- `national-excellence-data-qa`：通过内部 `double-high-qa` Workflow 进行双高只读问数

共同写作规则在 [instructions.md](.claude/workflows/writing-docx/instructions.md)，由writing-docx配置直接注入。预制模板按templateKey加载所选writing-guide.md及DOCX参考副本，Agent自主规划、取证和撰写；与上传模板、无模板共用OfficeCLI原生MCP、Office渲染/PDF读取、data及Artifact工具，不维护地图或专用报告流水线。原逐页来源与指标YAML保留，不确定内容用黄色说明；目录、事实和全文版式须实际检查，发布成功不代表内容审核通过，详见[文档工具决策](doc/ADR/029-native-office-document-tools.md)。

业务字段见[能力payload映射](doc/specs/capability-payload.md)；预制模板只传payload.templateKey，年份和要求放input.text。

[共享数据库资产](.claude/databases/README.md)包含18问及报告来源的参数化查询、口径、输出字段和核验。按主题YAML内嵌指标定义与SQL为唯一维护源，检索索引由Python生成；data工具保留模型写只读SQL能力，须可信策略及数据库账号范围同时允许。

[通用文档工具](doc/ADR/029-native-office-document-tools.md)、[数据库管理与工具](doc/specs/data-source-connections.md)、[前端及SDK产品流程](doc/specs/conversation-reporting-product.md)区分已实现功能和接入差距。

前端和Java按消息提交可选capabilityRef；不能提交Workflow、Skill、模型、MCP地址或工作目录。同一业务会话切换能力时，Python隔离各能力Client和工具上下文。

## 配置与安全

模型配置写在根.env；数据库包的source.json登记可用能力；databases.json的sources按source_key集中连接/授权和用户名密码，默认项目根config/databases.json，可由CCSDK_DATABASES_FILE指定，参见deploy/data-access.example.json。本版经用户确认将该JSON提交私有Codeup并打入镜像，修改后需重新构建部署；其他凭据及结果明细不提交。direct问数关闭内置文件/命令工具；普通Agent仍启用bypassPermissions，不构成生产多租户沙箱。

文档工具需要[OfficeCLI](https://github.com/iOfficeAI/OfficeCLI)可执行文件；默认从PATH启动，可用CCSDK_OFFICECLI_PATH指定位置。Linux镜像包含OfficeCLI、LibreOffice及中文字体；Windows渲染使用LibreOffice或已安装WPS。documents.render/read_pdf负责更新目录并另存DOCX与PDF、通过PDFium读取PDF页面；实际逐页验收仍由Agent完成，工具成功不代表内容审核通过。

撰写预算由可信`writing-docx/workflow.json`配置为100轮、30分钟上限，普通会话沿用部署默认值；上限不是目标耗时。可选生图配置`CCSDK_IMAGE_BASE_URL`、`CCSDK_IMAGE_API_KEY`、`CCSDK_IMAGE_MODEL`（默认`qwen-image-3.0`），通过百炼OpenAI Images接口供Agent按需调用；支持1至3张本轮参考图，不额外安装生图SDK。配置或密钥变更后重启Runtime，问数能力不挂载生图工具。

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
