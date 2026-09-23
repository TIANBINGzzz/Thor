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
| `python/data_access/` | 来源授权、连接、查询校验及结果 |
| `python/workflows/writing_docx/` | 可信模板与指南加载、参考副本 |
| `.claude/` | Workflow、Skill、模板、数据库语义和指标 |
| `python/tests/`、`deploy/` | 回归、容器构建与部署 |
| `config/`、`doc/` | 部署配置；契约、决策及必要核验记录 |

## 4. Subsystem responsibilities

- Java 管业务身份、租户、Capability/文件 ACL、业务会话和消息；Python 管已授权执行、SDK 上下文、运行记录及成果快照。
- `runtime/config.py` 解析能力与 Workflow 并装配工具；`direct` 为受限 SDK Run，`agent` 由 Agent 自主执行。没有 JS 工作流运行器或通用 DAG 引擎。
- 数据资产按库集中；`data_services.py` 为每 Run 绑定来源、规则和私有配置，查询及分页复用同 Run 结果。
- 文稿自主规划、取证、编辑及核验；OfficeCLI 编辑，LibreOffice 更新字段/导出 PDF，PDFium 提供分页核验。图表作为 Mermaid 正文交付。
- `artifact_delivery.py` 自动上传发布快照并保存文件状态；下载与上传通过 `file_service.py` 从 Nacos 读取服务端配置。Java 按 artifactId/fileId 关联业务消息和下载权限，不解析模型链接判断交付。

## 5. Dependency directions

入口 -> Runtime -> SDK Worker -> 模型 / MCP；核心运行时不依赖前端。流程知识留 Workflow，共享数据库知识留数据库包；授权来自可信控制面和配置，发现资产不授予权限。

## 6. Architectural invariants

- 前端只触发 Capability；省略能力归一为 conversation，本轮授权与上轮界面选择分开。Workflow、Skill、模型、MCP 及连接均为内部组成。
- 业务 Token、Run JWT、模型密钥用途分离，凭据不进入模型输入、公共事件或持久化日志；按 MCP 注入规则见工程要求。
- 业务会话、Run、SDK session、Client 和 SSE 连接生命周期分开；断开订阅不取消 Run，resume 不撤销工具副作用。
- 公共事件脱敏，状态显示由 `event_display.py` 统一维护；显示名称不授予工具权限。配置快照、结果引用及文件状态不得跨身份或 Run 串用。

## 7. Important boundaries/interfaces

- Java/Python 以 Run JWT、HTTP/SSE 及授权文件引用交互；字段与示例见 API 参考，跨系统语义见 Runtime 契约。
- 同 tenant、user、businessSessionId 的全部能力串行共用 SDK 历史；工具、规则或凭据变化时重建 Client 并恢复历史。重启恢复依赖 RunStore 和 SDK transcript。
- 能力目录只读且无需鉴权，Java 筛选用户可用能力；payload 不能覆盖执行配置或权限，预制模板由服务端解析，上传模板沿用附件授权。
- Runtime/Worker 通过 JSONL 通信；独立执行使用 query，持久执行由 SessionActor 的单一任务管理 Client。全部附件准备完成才请求模型。
- Python/MCP 的地址、工具范围和凭据映射由服务端确定；私有观测另需部署开关及 run.observe，不进入公共 SSE。
- 校园大脑为独立 Capability，复用 Agent 执行，不新增 Workflow；`.claude/capabilities/campus-brain-query/` 显式管理指令、按需知识和 MCP 参数，`tools/campus.py` 绑定本轮身份并过滤响应，见 [ADR-035](doc/ADR/035-campus-query-adapter.md)。

## 8. Cross-cutting concerns

- 安全：bypassPermissions 和单容器不构成租户沙箱；生产授权、撤销及文件/进程/网络隔离仍需独立验收。
- 持久化：`.scribe-runs/` 保存 RunStore、SDK 历史、数据结果和成果；终态只清理临时输入，整个目录不是可随意删除的缓存。磁盘保留、归档及总配额仍需管理。
- 可靠性：Run 与文件上传分别表达终态；上传结果不确定不自动重传。排队、文件准备、模型执行分别计时；重启不恢复在途进程。
- 部署：单副本、单 HTTP worker；默认数据库配置随私有源码及镜像交付，模型/JWT 密钥由运行环境注入；数据卷保留。操作与回滚见部署说明。

## 9. Where to look for X

| 内容 | 权威入口 |
| --- | --- |
| 开发与持续要求 | [AGENTS.md](AGENTS.md)、[工程要求](doc/specs/engineering-requirements.md) |
| HTTP 字段及示例 | [API 参考](doc/python-api.html)；校验：`python/runtime/protocol.py`、`auth.py` |
| 执行契约与业务映射 | [Runtime](doc/specs/ccsdk-runtime-interface.md)、[Java 职责](doc/specs/java-control-plane.md) |
| 配置与数据库 | [配置字段](config/README.md)、[数据契约](doc/specs/data-source-connections.md) |
| 执行规则 | [问数](.claude/workflows/double-high-qa/instructions.md)、[撰写](.claude/workflows/writing-docx/instructions.md) |
| 取舍与核验 | [ADR](doc/ADR/README.md)、[业务来源](doc/verification/report-source-audit.md)、[验收记录](doc/verification/acceptance.md) |
| 启动、构建和发布 | [部署说明](deploy/README.md)、`package.json`、`requirements.txt` |
