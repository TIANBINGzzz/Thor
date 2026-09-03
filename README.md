# CCSDKScribe

CCSDKScribe 是一个基于 Python Claude Agent SDK 的 Agent Runtime 和本地对话应用。项目支持普通对话、数据库问数、Skill/Workflow、MCP、文件处理和流式事件；模型可通过 Anthropic 兼容网关连接 Qwen 等提供方。

Python FastAPI 负责 Runtime、HTTP/SSE、本地会话、文件引用和 Agent 进程；Next.js 负责本地 Web UI；Node.js 仅用于前端、DBHub 和现有脚本。接入企业系统时，Java 应作为唯一业务控制面，浏览器不直接访问 Python、Claude SDK 或 MCP。

## 快速开始

```bash
cp .env.example .env
# 编辑 .env，填写 ANTHROPIC_AUTH_TOKEN、ANTHROPIC_BASE_URL、ANTHROPIC_MODEL

python -m pip install -r requirements.txt
npm run ui

# CLI 普通对话
npm start -- "分析这个项目当前具备哪些能力"

# CLI 报告
npm start -- "/report 为管理层撰写本项目技术能力与上线风险报告"

# 数据库演示
npm run db:demo -- "查询员工表字段，并统计员工人数"

# 测试
npm test
```

本地 UI 默认由统一启动器提供前端和 Python 服务；生产部署不要把本地 UI 接口当作 Java 多租户接口。

## 架构

```text
浏览器
   |
   v
Java 控制面（生产）
身份/租户/会话/消息/文件 ACL/能力注册/Run/统一 SSE
   |
   +--> DifyRuntimeAdapter ------> Dify API/SSE
   |
   +--> ClaudeRuntimeAdapter ----> Python Runtime
                                      |
                                      +--> query()：普通对话、问数、一次性任务
                                      |
                                      +--> SessionManager
                                                -> SessionActor（单一 asyncio Task）
                                                   -> ClaudeSDKClient：撰写、长任务、交互式 Skill
                                      |
                                      +--> ObservationRecorder -> 私有观测 Journal/Collector
```

Python Runtime 内部还会按能力配置加载 Workflow、Skill、MCP 和工作目录。`query()` 是一次独立 Run；`ClaudeSDKClient` 是由单个 SessionActor 独占的持久 Runtime。`ObservationRecorder` 在同一次 SDK 消息消费中读取原始消息，再分别生成私有详细观测和公共脱敏事件，不会通过第二次模型或工具调用补采集。Conversation、Claude Session、Agent Run、Client Runtime、观测流、asyncio Task 和浏览器连接的生命周期必须分开管理。

详细的接口、字段、鉴权、Token 透传、文件、重连、Workflow/Skill 和 Java 改造要求见：

[CCSDK Runtime 接口与字段规范](docs/specs/ccsdk-runtime-interface.md)

[Java 控制面接入方案](docs/specs/java-control-plane.md)

## 项目结构

```text
CCSDKScribe/
├── .claude/
│   ├── skills/              # Skill 定义
│   ├── agents/              # Agent/Subagent 定义
│   ├── workflows/           # Workflow profile 和编排脚本
│   └── commands/            # 命令入口
├── python/
│   ├── server.py            # FastAPI、SSE 和 Runtime API
│   ├── ui.py                # 本地 UI 启动编排
│   ├── agent_worker.py     # Claude SDK 消息/事件适配
│   ├── runtime/             # 协议、鉴权、RunStore、进程和配置编译
│   ├── tools/               # DOCX、artifact 等工具
│   └── local/               # 本地 UI 专用会话和文件服务
├── web/                     # Next.js + assistant-ui 前端
├── docs/
│   ├── specs/               # 接口和字段规范
│   └── ADR/                 # 架构决策记录
├── CLAUDE.md
├── AGENTS.md
└── backlog.md
```

## 配置

模型网关：

```dotenv
ANTHROPIC_AUTH_TOKEN=你的网关密钥
ANTHROPIC_BASE_URL=https://你的兼容网关地址/apps/anthropic
ANTHROPIC_MODEL=qwen3.7-flash
SCRIBE_MODELS=qwen3.7-flash,qwen3.7-plus
```

数据库问数配置位于 `.claude/workflows/database-qa/`。实际数据库账号放在被 Git 忽略的 `workflow.env`，使用只读账号，不要把密码、业务 Token 或真实数据写入 Skill、Workflow 文档和提交记录。

## 生产部署建议

最小生产拓扑：

| 组件 | 职责 |
| --- | --- |
| Java 服务 | 登录身份、租户和资源 ACL、业务会话/消息、能力注册、Run/Event 元数据、统一浏览器 SSE |
| Python Runtime | 验证 Run JWT、执行 `query()` 或 SessionActor/`ClaudeSDKClient`、采集私有观测、翻译脱敏事件 |
| 业务数据库 | 保存 Conversation、Message、Run、Event 索引、文件和 Artifact 元数据 |
| Redis | 多实例下的 `jti` 防重放、事件流、活动 Run、租约和订阅协调 |
| 对象存储 | 用户文件、Workspace 输入和生成 Artifact |
| Transcript 持久卷 | Claude SDK transcript；仅用于 `runtimeSessionRef` 的上下文恢复 |
| 私有观测 Journal/Collector | 加密保存受控的 SDK 详细观测；按租户、运维和审计权限读取，不接入浏览器 SSE |
| Worker/容器 | 每 Run 或每 SessionActor 的进程、网络、文件系统和 MCP 隔离 |

单机 PoC 可以使用 Java + Python sidecar、本地 SQLite 和本地卷。多实例生产建议使用 Docker Compose 或 Kubernetes，并将 Java 业务库、Redis、对象存储和 Runtime transcript 卷分开授权。浏览器断开只取消订阅，不应默认取消后台 Run；刷新后由 Java 按 `runId` 和事件序号重新订阅。

## 安全边界

- 浏览器只提交业务会话、文本、已登记文件 ID 和受控 `capabilityRef`。
- Java 从登录上下文取得 `userId`、`tenantId`，校验会话、文件和能力权限，再签发短期 Run JWT。
- Python 校验签名、`iss`、`aud`、`exp`、`jti`、`scope`，并确认 JWT 与请求的 `runId`/`capabilityRef` 一致。
- 只有声明需要业务凭据的 MCP 才接收 `credentials.platformBearer`；Python 按 `MCP_AUTH_RULES` 注入 HTTP Header 或 stdio 环境变量。
- 业务 Token、模型密钥和其他原始凭据不得写入任何观测或业务持久化；它们只在授权链路中短暂使用。完整思考内容、原始工具参数和工具结果不得进入浏览器事件、Prompt、Java 业务库或普通应用日志；经凭据脱敏、大小限制和权限隔离后，可进入独立的私有观测 Journal/Collector。
- 私有观测不属于公共事件回放源，只允许受限的运维/审计身份读取，并按租户、用户、能力和保留期限授权。
- 当前 `bypassPermissions` 和单进程状态只适合内网验证；开放代码执行、多租户或任意文件访问前必须增加容器/等价沙箱和外部状态存储。

## 当前状态

已具备：

- Python Claude Agent SDK 的 `query()` Run
- `agent-run/v1` 请求校验和 `agent-events/v1` 脱敏事件
- Run 状态、事件序号回放、SSE 心跳和取消接口
- Workflow profile、Skill、MCP 配置和按规则的 Token 注入
- 本地会话、上传文件、DOCX 工具和 Next.js 对话界面
- 项目 Skill 通过文件维护并支持 `@skill:` 引用；Web 工作区不再提供 Skill 创建向导或入口
- Java 控制面接入所需的协议设计和适配器边界
- 私有观测字段、公共事件分流和 `ccsdk-observation/v1` 目标契约（观测 Recorder/Journal 尚未实现）

尚需补齐：

- `SessionManager -> SessionActor -> ClaudeSDKClient` 的长连接实现
- `ObservationRecorder`、私有 Journal/Collector、脱敏和观测查询授权
- Java Run/Event 持久化、活动 Run 查询和刷新重连
- File Broker、对象存储、Artifact 生命周期和跨租户 ACL
- Redis 多实例调度、运行租约和生产级 replay cache
- RS256/EdDSA、mTLS 和容器权限隔离
- `professional-report.js` 的显式 Workflow Runner

## 文档

- [Runtime 接口与字段规范](docs/specs/ccsdk-runtime-interface.md)
- [Java 控制面接入方案](docs/specs/java-control-plane.md)
- [Python 应用后端 ADR](docs/ADR/011-python-application-backend.md)
- [Provider-neutral Runtime ADR](docs/ADR/012-provider-neutral-agent-runtime.md)
- [Java-Python Runtime Contract ADR](docs/ADR/013-java-python-runtime-contract.md)
- [CCSDK Runtime MVP ADR](docs/ADR/014-ccsdk-runtime-mvp.md)
- [Query 与 SDKClient 生命周期 ADR](docs/ADR/015-query-client-runtime-lifecycle.md)
- [开发计划](backlog.md)

## 测试

```bash
npm test
python -m compileall python
```

## 许可

MIT
