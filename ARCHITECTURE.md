# 架构

本文件只维护以下九部分；开发规则见 [AGENTS.md](AGENTS.md)，接口字段不在此重复。生产目标不代表已经验收。

## 1. System purpose

供 Java 调用的 Python Claude Agent SDK Runtime，执行对话、问数、图表、图像及文档撰写能力。

## 2. System context

业务前端 -> Java 控制面 -> Python Runtime -> SDK -> 模型 / MCP。Java 可另行选择 Dify 等外部后端；Java、业务存储和前端不在本仓库。

配置存储使用 MySQL；当前唯一业务数据来源是校双高 `schoolDoubleHigh`，`hpm` 为业务域；来源标识不改变物理库、查询口径或访问权限。

## 3. Top-level codemap

| 目录 | 职责 |
| --- | --- |
| `python/server.py`、`agent_worker.py` | HTTP/SSE 入口、Run 调度及 SDK 子进程 |
| `python/runtime/` | 协议、鉴权、装配、Actor、存储、文件传输与事件 |
| `python/tools/` | 数据、搜索、图表、生图、文档阅读/渲染和发布工具 |
| `python/capability_packs/<capabilityRef>/` | 随部署交付的能力业务代码；`pack.json` 登记 Schema，`operations.py` 提供动作，必要时设内部 Service |
| `python/data_access/` | 客户数据范围、连接、查询校验及结果 |
| `python/runtime/template_assets.py` | 可信模板与指南加载、参考副本 |
| `python/runtime/prompt_assembly.py` | 显式提示词资产的统一加载、过滤、渲染及来源说明 |
| `.claude/` | 公共提示词、工具规则、模板及数据库知识；可编辑能力与 Skill 在 MySQL |
| `python/tests/`、`deploy/` | 回归、容器构建与部署 |
| `config/`、`doc/` | 部署配置；契约、工程要求、决策及必要核验记录 |
| `deploy/environments.local.md` | 本机私有环境连接与部署交接资料；不提交 Git、不打入镜像、不写入日志 |

## 4. Subsystem responsibilities

- Java 管业务身份、租户、Capability/文件 ACL、业务会话和消息；Python 管已授权执行、SDK 上下文、运行记录及成果快照。
- `config_store.py` 从 MySQL 一次一致性读取，`configuration.py` 装配当轮能力、Skill、模型、数据库、MCP 和预算；`config_api.py` 通过独立管理鉴权保存即生效。`capabilities.py` 提供最新公开目录，`prompt_assembly.py` 统一加载数据库正文与部署的公共规则、模板/工具知识。按需 Skill 写入本轮工作区，必载 Skill 注入全文。配置固定到 Run 结束，下一 Run 重新读取；不设置发布表、版本仓库或本地 fallback。
- `.claude/tools/<名称>/tool.json` 集中声明分类、操作 Schema、实现契约和显示规则；远端 MCP 连接及凭据规则来自 MySQL。`tool_catalog.py` 校验元数据，`tool_registry.py` 登记可信 Provider；`mcp_providers.py` 通用装配 HTTP/stdio MCP，进程内工具留在 `python/tools/`。MCP operation 从 Agent 视角就是 Tool；Service 仅在需要复用状态或实现时设立，不要求一一对应。动态操作和外部 MCP 只声明 namespace，不伪造静态 schema。
- 源码能力可用 `operationRefs` 选择同名代码包的业务动作；目录发现只读静态声明，Worker 经 `capability_packs/registry.py` 加载代码，`capability_operations.py` 校验输入输出并适配为 `capability_ops` MCP Tool。操作复用本轮数据、文档及成果 Service，使用数据不必向模型开放通用数据 Tool；不为业务场景新建 Provider。
- 数据资产按库集中；`data_services.py` 为每 Run 绑定来源、规则和私有配置，查询及分页复用同 Run 结果。
- 文稿自主规划、取证、编辑及核验；OfficeCLI 编辑，LibreOffice 更新字段/导出 PDF，PDFium 提供分页核验。图表作为 Mermaid 正文交付。
- `artifact_delivery.py` 自动上传发布快照并保存文件状态；`file_download.py` 仅从平台文件服务准备附件；`bootstrap.py` 在入口导入前通过 `application_config.py` 校验完整启动 YAML，再连接 MySQL；`deployment_config.py` 校验启动设置并按 Run 绑定配置、解析选定引用，文件/MCP 边界各自校验注入结果。Java 按 artifactId/fileId 关联业务消息和下载权限，不解析模型链接判断交付。
- Capability、提示词、Tool/Service 及能力代码的归属规范见[工程要求 REQ-002](doc/specs/engineering-requirements.md#req-002前端触发-capability执行资产保持内部化)；固定流程是否可由 Agent 保证，按该要求区分模型决策和服务端执行。

## 5. Dependency directions

入口 -> Runtime -> SDK Worker -> 模型 / MCP；能力业务代码 -> 本轮通用 Service，核心运行时不依赖具体能力实现或前端。业务规则留 Capability，共享数据库知识留数据库包；授权来自可信控制面，数据库范围按来源登记并逐轮解析业务身份，发现资产不授予权限。

## 6. Architectural invariants

- 前端只触发 Capability；省略能力归一为 conversation，本轮授权与上轮界面选择分开。Workflow、Skill、模型、MCP 及连接均为内部组成。
- 业务 Token、Run JWT、模型密钥用途分离，凭据不进入模型输入、公共事件或持久化日志；按 MCP 注入规则见工程要求。
- 业务会话、Run、SDK session、Client 和 SSE 连接生命周期分开；断开订阅不取消 Run，resume 不撤销工具副作用。
- 集成约定：待发送列表及排序、暂停由前端本地管理，Java 授权并保存实际提交的消息；Python 保留已提交 Run 的串行执行调度。文本引导仅通过 steer 追加到活动 Run，默认不打断在途工具，回执随原 Run SSE 推送及补放；停止仍走 cancel。前端队列接入另行实现，边界见 [Runtime 契约](doc/specs/ccsdk-runtime-interface.md#4-run-查询与控制模块)。
- 公共事件脱敏，状态显示由 `event_display.py` 统一维护；显示名称不授予工具权限。配置快照、结果引用及文件状态不得跨身份或 Run 串用。
- 能力代码是可信部署代码，不是沙箱插件；只有与已部署代码包同名的能力可以选择已登记 Operation。代码随 Worker 生命周期加载，部署变更须重启 Worker，不提供在线换码或源码快照。Operation 绑定本轮上下文，取消和收尾完成前不得复用，详见 [ADR-037](doc/ADR/037-capability-owned-operations.md)。

## 7. Important boundaries/interfaces

- Java/Python 以 Run JWT、HTTP/SSE 及授权文件引用交互；字段与示例见 API 参考，跨系统语义见 Runtime 契约。
- 同 Run JWT tenant、sub、businessSessionId 的全部能力串行共用 SDK 历史；RunStore 原子绑定身份与随机工作区，已有目录就地登记。模型、思考预算、effort、模型环境、附加目录、规则和 MCP 按轮热更新，凭据按轮绑定清理，Hook 校验本轮工具授权；仅固定启动参数变化时重建并恢复历史，重启恢复依赖 RunStore 和 SDK transcript。
- 公开能力目录只读且无需鉴权，Java 筛选用户可用能力；payload 不能覆盖执行配置或权限，预制模板由服务端解析，上传模板沿用附件授权。能力配置从 MySQL 读取，第三方可信后端通过独立管理 API 修改。工具实现、模板和数据知识随部署维护，管理端不能上传代码。
- Runtime/Worker 通过 JSONL 通信；独立执行使用 query，持久执行由 SessionActor 的单一任务管理 Client。全部附件准备完成才请求模型。
- `runtime/worker_pool.py` 预连接空白 SDK Client，所有能力共用基础工具白名单，业务 MCP 与规则逐轮装配；direct/agent 切换本身不分组或重连，其他固定启动配置不同仍按指纹匹配并在必要时恢复历史。各组共享6个库存，首轮匹配后独占领取；活跃会话复用，历史恢复冷启动。容量不足时按完成且清理后的空闲时间回收最久未互动 Client，保护新输入和在途请求，进程退出才释放名额；保留历史，不跨会话归还。工具约束见 Runtime 契约，限制及内存保护见配置字段。
- Python/MCP 的地址、工具范围和凭据映射由服务端确定；私有证据统一进入有界观测日志，不进入公共 SSE 或业务 RunStore；采集读取由专用短时 JWT 和单独环境密钥授权。
- 校园大脑为独立 Capability，复用 Agent 执行，不新增 Workflow；`.claude/capabilities/campus-brain-query/` 保留业务词表与工具输入输出约束；可编辑指令与 MCP 连接在 MySQL，`python/capability_packs/campus-brain-query/operations.py` 提供可信业务 Operation 与内部 Service，`runtime/mcp_auth.py` 管理通用凭据参数映射，`runtime/mcp_transport.py` 负责 HTTP 传输，见 [ADR-035](doc/ADR/035-campus-query-adapter.md) 和 [ADR-037](doc/ADR/037-capability-owned-operations.md)。

## 8. Cross-cutting concerns

- 安全：bypassPermissions 和单容器不构成租户沙箱；生产授权、撤销及文件/进程/网络隔离仍需独立验收。
- 持久化：`.scribe-runs/` 保存 RunStore、SDK 历史、数据结果及成果；能力配置由 MySQL 提供。终态只清理临时输入，整个目录不是可随意删除的缓存。磁盘保留、归档及总配额仍需管理。
- 观测：`runtime/observability.py` 保留本地 Timing、里程碑和预热关联的有界待采日志，通过通用接口供各观测平台主动拉取；长期事件、Trace 和指标库由平台维护，Runtime 不依赖 Hawkeye、Phoenix 或 Prometheus。总开关在 MySQL ccsdk_setting 的 `runtime_observation_enabled`，重启生效；关闭时不建观测库或写入线程，故障不阻断业务。采集范围为 Python Runtime、Actor、Worker 及其可观察的工具和成果阶段；不采集浏览器接收/渲染或 Java 阶段。拉取接口用独立观测 JWT。
- 可靠性：Run 与文件上传分别表达终态；上传结果不确定不自动重传。排队、文件准备、模型执行分别计时；重启不恢复在途进程。
- 部署：单副本、单 HTTP worker；一客户一套 Runtime。MySQL 是可编辑配置与秘密的唯一来源，application.yml 只管配置库引导及宿主机参数，不加载 env 或 .local 覆盖。能力及连接在下一 Run 更新，启动对象和入口常量排空后重启；保留数据卷。边界见配置说明。

## 9. Where to look for X

| 内容 | 权威入口 |
| --- | --- |
| 开发与持续要求 | [AGENTS.md](AGENTS.md)、[工程要求](doc/specs/engineering-requirements.md) |
| HTTP 字段及示例 | [API 参考](doc/python-api.html)；校验：`python/runtime/protocol.py`、`auth.py` |
| 执行契约与业务映射 | [Runtime](doc/specs/ccsdk-runtime-interface.md) |
| 配置与数据库 | [配置字段](config/README.md)、[数据契约](doc/specs/data-source-connections.md) |
| 执行规则 | MySQL `ccsdk_capability.prompt/指令列`、`ccsdk_skill`；[装配入口](python/runtime/prompt_assembly.py) |
| Agent 编码与能力资产归属 | [工程要求 REQ-002](doc/specs/engineering-requirements.md#req-002前端触发-capability执行资产保持内部化) |
| 本机环境连接与部署交接 | `deploy/environments.local.md`（私有文件，不提交、不进镜像、不进日志） |
| 取舍与核验 | [ADR](doc/ADR/README.md)、[业务来源](doc/verification/report-source-audit.md)、[验收记录](doc/verification/acceptance.md) |
| 启动、构建和发布 | [部署说明](deploy/README.md)、`package.json`、`requirements.txt` |
