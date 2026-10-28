# 架构

本文件只维护以下九部分；开发规则见 [AGENTS.md](AGENTS.md)，接口字段不在此重复。生产目标不代表已经验收。

## 1. System purpose

供 Java 调用的 Python Claude Agent SDK Runtime，执行对话、问数、图表、图像及文档撰写能力。

## 2. System context

业务前端 -> Java 控制面 -> Python Runtime -> SDK -> 模型 / MCP。Java 可另行选择 Dify 等外部后端；Java、业务存储和前端不在本仓库。

当前唯一数据库是校双高 `schoolDoubleHigh`，`hpm` 为业务域；来源标识不改变物理库、查询口径或访问权限。

## 3. Top-level codemap

| 目录 | 职责 |
| --- | --- |
| `python/server.py`、`agent_worker.py` | HTTP/SSE 入口、Run 调度及 SDK 子进程 |
| `python/runtime/` | 协议、鉴权、装配、Actor、存储、文件传输与事件 |
| `python/tools/` | 数据、搜索、图表、生图、文档阅读/渲染和发布工具 |
| `python/capability_packs/<capabilityRef>/` | 随部署交付的能力业务代码；`pack.json` 登记 Schema，`operations.py` 提供动作，必要时设内部 Service |
| `python/data_access/` | 来源授权、连接、查询校验及结果 |
| `python/runtime/template_assets.py` | 可信模板与指南加载、参考副本 |
| `python/runtime/prompt_assembly.py` | 显式提示词资产的统一加载、过滤、渲染及来源说明 |
| `.claude/` | Capability 入口、Skill、工具规则、模板及数据库知识 |
| `python/tests/`、`deploy/` | 回归、容器构建与部署 |
| `config/`、`doc/` | 部署配置；契约、工程要求、决策及必要核验记录 |
| `deploy/environments.local.md` | 本机私有环境连接与部署交接资料；不提交 Git、不打入镜像、不写入日志 |

## 4. Subsystem responsibilities

- Java 管业务身份、租户、Capability/文件 ACL、业务会话和消息；Python 管已授权执行、SDK 上下文、运行记录及成果快照。
- `capabilities.py` 动态发现 `capabilities/<名称>/capability.json`，按能力及依赖资产的文件签名缓存已校验目录，发布后主动失效；`prompt_assembly.py` 加载公共规则、能力正文和显式指引、所选模板、Skill 及实际挂载工具的指引。Skill 默认仅注入用途和读取路径，`requiredSkillRefs` 显式注入全文；声明不授予工具权限。`config.py` 将同一装配结果用于 default/custom 模式及逐轮 Hook；有状态工具由 `tool_services.py` 绑定清理。`direct` 是受限 SDK Run，`agent` 自主执行；没有 Workflow 目录、通用 DAG 引擎或完整资产版本快照系统。
- `.claude/tools/<名称>/tool.json` 集中声明分类、操作 Schema、MCP 连接、凭据目标和显示规则。`tool_catalog.py` 校验元数据，`tool_registry.py` 登记可信 Provider；`mcp_providers.py` 通用装配 HTTP/stdio MCP，进程内工具留在 `python/tools/`。MCP operation 从 Agent 视角就是 Tool；Service 仅在需要复用状态或实现时设立，不要求一一对应。动态操作和外部 MCP 只声明 namespace，不伪造静态 schema。
- 源码能力可用 `operationRefs` 选择同名代码包的业务动作；目录发现和预览只读静态声明，Worker 经 `capability_packs/registry.py` 加载代码，`capability_operations.py` 校验输入输出并适配为 `capability_ops` MCP Tool。操作复用本轮数据、文档及成果 Service，使用数据不必向模型开放通用数据 Tool；不为业务场景新建 Provider。
- 数据资产按库集中；`data_services.py` 为每 Run 绑定来源、规则和私有配置，查询及分页复用同 Run 结果。
- 文稿自主规划、取证、编辑及核验；OfficeCLI 编辑，LibreOffice 更新字段/导出 PDF，PDFium 提供分页核验。图表作为 Mermaid 正文交付。
- `artifact_delivery.py` 自动上传发布快照并保存文件状态；`deployment_config.py` 统一解析部署配置引用并生成选定值快照，`nacos_config.py` 只负责配置中心连接，文件/MCP 边界各自校验注入结果。Java 按 artifactId/fileId 关联业务消息和下载权限，不解析模型链接判断交付。
- Capability、提示词、Tool/Service 及能力代码的归属规范见[工程要求 REQ-002](doc/specs/engineering-requirements.md#req-002前端触发-capability执行资产保持内部化)；固定流程是否可由 Agent 保证，按该要求区分模型决策和服务端执行。

## 5. Dependency directions

入口 -> Runtime -> SDK Worker -> 模型 / MCP；能力业务代码 -> 本轮通用 Service，核心运行时不依赖具体能力实现或前端。业务规则留 Capability，共享数据库知识留数据库包；授权来自可信控制面和部署策略，发现资产不授予权限。

## 6. Architectural invariants

- 前端只触发 Capability；省略能力归一为 conversation，本轮授权与上轮界面选择分开。Workflow、Skill、模型、MCP 及连接均为内部组成。
- 业务 Token、Run JWT、模型密钥用途分离，凭据不进入模型输入、公共事件或持久化日志；按 MCP 注入规则见工程要求。
- 业务会话、Run、SDK session、Client 和 SSE 连接生命周期分开；断开订阅不取消 Run，resume 不撤销工具副作用。
- Java 负责持久化消息与下一 Run 排队；文本引导只追加到活动 Run 的 SDK 会话，不新建 Run、不改变当前授权，默认不打断在途工具。停止仍走 cancel。
- 公共事件脱敏，状态显示由 `event_display.py` 统一维护；显示名称不授予工具权限。配置快照、结果引用及文件状态不得跨身份或 Run 串用。
- 能力代码是可信部署代码，不是沙箱插件；持久化能力不得引用代码包。代码随 Worker 生命周期加载，部署变更须重启 Worker，不提供在线换码或源码快照。Operation 绑定本轮上下文，取消和收尾完成前不得复用，详见 [ADR-037](doc/ADR/037-capability-owned-operations.md)。

## 7. Important boundaries/interfaces

- Java/Python 以 Run JWT、HTTP/SSE 及授权文件引用交互；字段与示例见 API 参考，跨系统语义见 Runtime 契约。
- 同 Run JWT tenant、sub、businessSessionId 的全部能力串行共用 SDK 历史；RunStore 原子绑定身份与随机工作区，已有目录就地登记。模型、思考预算、effort、模型环境、附加目录、规则和 MCP 按轮热更新，凭据按轮绑定清理，Hook 校验本轮工具授权；仅固定启动参数变化时重建并恢复历史，重启恢复依赖 RunStore 和 SDK transcript。
- 公开能力目录只读且无需鉴权，Java 筛选用户可用能力；payload 不能覆盖执行配置或权限，预制模板由服务端解析，上传模板沿用附件授权。`asset_management.py` 提供独立管理 JWT 保护的目录、校验、新建及有效指令预览接口，只组合已登记资产。预览复用编译器，标明假定工具、来源、排除原因和运行时占位，不实例化 Provider 或连接业务系统；Java 管理页面需另行接入。工具连接及数据库授权由部署端维护。
- Runtime/Worker 通过 JSONL 通信；独立执行使用 query，持久执行由 SessionActor 的单一任务管理 Client。全部附件准备完成才请求模型。
- `runtime/worker_pool.py` 按固定启动配置分组预连接空白 SDK Client，direct 不加载内置工具，agent 使用代码白名单；跨组切换重建并恢复历史。各组共享6个库存，首轮匹配后独占领取；活跃会话复用，历史恢复冷启动。容量不足时按完成且清理后的空闲时间回收最久未互动 Client，保护新输入和在途请求，进程退出才释放名额；保留历史，不跨会话归还。工具约束见 Runtime 契约，限制及内存保护见配置字段。
- Python/MCP 的地址、工具范围和凭据映射由服务端确定；私有证据统一进入有界观测日志，不进入公共 SSE 或业务 RunStore；采集读取由专用短时 JWT 和单独环境密钥授权。
- 校园大脑为独立 Capability，复用 Agent 执行，不新增 Workflow；`.claude/capabilities/campus-brain-query/` 显式管理指令、按需知识和 MCP 参数，`python/capability_packs/campus-brain-query/operations.py` 提供可信业务 Operation 与内部 Service，`runtime/mcp_auth.py` 管理通用凭据参数映射，`runtime/mcp_transport.py` 负责 HTTP 传输，见 [ADR-035](doc/ADR/035-campus-query-adapter.md) 和 [ADR-037](doc/ADR/037-capability-owned-operations.md)。

## 8. Cross-cutting concerns

- 安全：bypassPermissions 和单容器不构成租户沙箱；生产授权、撤销及文件/进程/网络隔离仍需独立验收。
- 持久化：`.scribe-runs/` 保存 RunStore、SDK 历史、数据结果、成果及管理端新建能力（`capabilities/`）；后者与源码能力合并发现、禁止重名覆盖，复用源码 Skill。终态只清理临时输入，整个目录不是可随意删除的缓存。磁盘保留、归档及总配额仍需管理。
- 观测：`runtime/observability.py` 保留本地 Timing、里程碑和预热关联的有界待采日志，通过通用接口供各观测平台主动拉取；长期事件、Trace 和指标库由平台维护，Runtime 不依赖 Hawkeye、Phoenix 或 Prometheus。总开关在 `config/application.yml` 的 `runtime.observability.enabled`；关闭时不建观测库或写入线程，故障不阻断业务。采集范围为 Python Runtime、Actor、Worker 及其可观察的工具和成果阶段；不采集浏览器接收/渲染或 Java 阶段。拉取接口用独立观测 JWT。
- 可靠性：Run 与文件上传分别表达终态；上传结果不确定不自动重传。排队、文件准备、模型执行分别计时；重启不恢复在途进程。
- 部署：单副本、单 HTTP worker；默认数据库配置随私有源码及镜像交付，模型/JWT 密钥由运行环境注入；数据卷保留。操作与回滚见部署说明。

## 9. Where to look for X

| 内容 | 权威入口 |
| --- | --- |
| 开发与持续要求 | [AGENTS.md](AGENTS.md)、[工程要求](doc/specs/engineering-requirements.md) |
| HTTP 字段及示例 | [API 参考](doc/python-api.html)；校验：`python/runtime/protocol.py`、`auth.py` |
| 执行契约与业务映射 | [Runtime](doc/specs/ccsdk-runtime-interface.md) |
| 配置与数据库 | [配置字段](config/README.md)、[数据契约](doc/specs/data-source-connections.md) |
| 执行规则 | [问数](.claude/capabilities/national-excellence-data-qa/CAPABILITY.md)、[撰写](.claude/capabilities/document-writing/CAPABILITY.md) |
| Agent 编码与能力资产归属 | [工程要求 REQ-002](doc/specs/engineering-requirements.md#req-002前端触发-capability执行资产保持内部化) |
| 本机环境连接与部署交接 | `deploy/environments.local.md`（私有文件，不提交、不进镜像、不进日志） |
| 取舍与核验 | [ADR](doc/ADR/README.md)、[业务来源](doc/verification/report-source-audit.md)、[验收记录](doc/verification/acceptance.md) |
| 启动、构建和发布 | [部署说明](deploy/README.md)、`package.json`、`requirements.txt` |
