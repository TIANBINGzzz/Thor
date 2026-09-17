# ARCHITECTURE.md

仅维护以下九部分：目的、上下文、代码地图、职责、依赖、不变量、边界、横切关注点和查找入口；不展开接口字段、操作教程或待办。生产目标不代表已完成验收。

## 1. System purpose

ccagentsdk 是供 Java 调用的 Python Claude Agent SDK Runtime，支持对话、Workflow/Skill、MCP、文件处理和流式事件。

## 2. System context

```text
本地：独立 ScribePlayground -> Python Runtime -> SDK -> 模型 / MCP
生产目标：业务前端 -> Java 控制面 -> Python Runtime -> SDK -> 模型 / MCP
                                └-> Dify 适配器（外部执行后端）
```

Java、ScribePlayground 及其业务存储均不在本仓库；两者通过相同 Runtime HTTP 契约接入。

当前唯一数据库为校双高数据库schoolDoubleHigh，hpm为业务域。资产已按库集中，首期单租户多来源；旧qa_db/report_db登记仅见Git历史，命名不改变查询筛选口径。

## 3. Top-level codemap

```text
python/       后端与 SDK 执行
  runtime/    协议、鉴权、配置、Run、Actor
  tools/      data、DOCX、Artifact通用工具入口
  data_access/ 来源授权、连接、查询、结果及Run上下文
  workflows/writing_docx/ 可信模板及指南加载、参考副本、可选地图维护工具
  tests/      后端测试
.claude/      skills/、agents/、commands/、workflows/执行资产；databases/按库共享语义和查询
deploy/       单实例容器构建、部署脚本及配置示例
config/       本地默认部署配置（忽略）；databases.json集中连接/授权，certificates/保存CA
doc/         specs/ 规范、ADR/ 决策、静态 API HTML
```

## 4. Subsystem responsibilities

- Java 控制面：业务身份、租户、资源 ACL、Capability、会话/文件和审计。
- `python/server.py`：Java HTTP/SSE 与 Run 调度；`runtime/`：执行配置、状态、存储与生命周期。
- `python/agent_worker.py`：调用 SDK、消费消息并向父 Runtime 上送事件；`tools/`：具体工具实现。
- `.claude/workflows/<name>/`：流程 profile、专属约束和模板；目标按来源标识引用数据库资产。
- `.claude/databases/<source_key>/source.json`登记来源和能力绑定；schema/维护表列类型及说明，metrics/<domain>/按主题YAML内嵌定义和SQL并自动生成索引，semantics/维护关联及业务规则。测试在python/tests/databases/；部署侧databases.json按source_key集中连接/授权，不进入镜像或模型资产快照。
- `data_access/`管理来源授权、连接、查询及结果；`runtime/data_services.py`装配Run数据服务。可信Workflow注入共同Skill及所选指南，冻结实际DOCX指纹并提供工作目录副本；Agent自主规划、取证、编辑和验收，统一使用通用DOCX、文件、代码及Artifact工具。地图和取数计划只作维护参考，指标含义和SQL只放数据库包；上传模板作结构/样式参考，不登记地图。发布工具校验文件边界，不代替业务与版式核验。
- 外部 `ScribePlayground`：测试页面、模拟 Java 的会话/上传/File Broker 与测试 JWT 签发，不包含 SDK 执行。

## 5. Dependency directions

调用方向：入口 → Runtime → SDK Worker → 模型 / MCP；Runtime 配置层加载执行资产并装配工具。
核心运行时不依赖Web展示；流程知识留在Workflow，共享数据库知识留数据库包，不写入通用Python。授权来自可信控制面/静态配置，模型不得提升权限；发现数据库包不等于获得访问权。

## 6. Architectural invariants

- 普通会话可省略capabilityRef，内部归一为conversation；选择能力仅作用于本轮，JWT仍绑定具体能力。Workflow/Skill/Agent/连接均为内部组成。
- 业务 Token、Run JWT、模型密钥用途分离；业务 Token 仅按规则注入选定 MCP，不进入模型输入或持久化。
- 业务会话、Run、SDK session、Client 和浏览器连接生命周期分离；断开 SSE 不等于取消 Run。
- 公共事件统一脱敏，凭据和执行状态不得跨用户/租户串用。

这些是必须守住的要求；Capability 解耦等现存差距见工程要求清单，不能把目标当作已实现。

## 7. Important boundaries/interfaces

- Java ↔ Python：内部 Run 协议、Run JWT、状态/事件及取消；完整字段见 Runtime 规范。
- Java持有业务会话与消息；Python按tenant、user和businessSessionId分页查询现有Run执行摘要，使用独立session.read授权，不引入业务SessionStore或暴露SDK会话信息。
- 能力目录是无需鉴权的只读接口，返回已登记业务标识；Java负责用户可用列表。Run payload承载业务数据；已登记的templateKey由服务端解析为可信模板资源，不允许覆盖执行配置或权限。上传模板沿用授权附件作撰写参考；共同Skill按模板加载说明的[实现](doc/ADR/025-unified-template-writing.md)不新增请求字段。
- RunStore 内部记录与 HTTP 响应分离；身份用于 Python 归属校验，SDK Session 与执行元数据不返回 Java。
- Run 身份仅取自已验证 Run JWT 的 `tenant`、`sub`；请求正文不重复声明身份，业务 MCP Token 不作为身份来源。
- 父 Runtime ↔ Worker：JSONL 进程边界；独立执行使用 `query()`，持久执行由 SessionActor 独占 Client。
- Python ↔ MCP：受控服务器配置和按 MCP 注入的凭据；规则不由浏览器或模型提供。
- 业务文件 ↔ Runtime 工作目录：通过授权引用获取输入；本地路径不能替代文件 ACL。
- Run 内先准备全部附件，再查询 SDK；无附件直接执行。Client 的准备和清理随会话串行，准备可取消；排队、文件准备、模型执行分别计时，文件进度复用公共 SSE。

## 8. Cross-cutting concerns

- 安全：当前 `bypassPermissions` 和路径约定不构成生产沙箱；多租户需文件、进程、网络及凭据隔离。
- 可靠性与观测：Run 状态、事件回放、超时、取消和 Client 恢复分别管理；运行事件通过 RunStore 管理。
- 数据生命周期：`.scribe-runs/`含运行记录、SDK会话、data物化结果和文档成果；每Run绑定身份、包及策略快照，不共享结果引用。业务会话/上传由Java管理，运行数据不是可整体删除的缓存。
- 临时内容：`.tmp/`、`scratch/` 用于临时验证/笔记，清理前确认无占用和唯一成果；依赖与构建缓存可重建。
- 容量：局部限额不等于磁盘总配额；运行数据仍需保留、归档和清理策略。
- 部署：deploy/提供云效Linux试运行模板；构建测试并导出镜像，部署主机生成配置或保留学校现场配置。集中配置目录只读挂载到容器/app/config，CCSDK_DATABASES_FILE定位databases.json；公开资产随镜像交付，命名卷保存运行数据。换Key需排空并重建；单副本单HTTP worker，容器不代表租户隔离或生产验收。

## 9. Where to look for X

| 内容 | 入口 |
| --- | --- |
| 启动与依赖 | `README.md`、`package.json`、`requirements.txt` |
| Java 接口与职责 | [Java 业务层设计规范](doc/specs/java-control-plane.md)、[Runtime 规范](doc/specs/ccsdk-runtime-interface.md)、[Python API HTML](doc/python-api.html) |
| 独立本地自测 | `../ScribePlayground/README.md`、[拆分决策](doc/ADR/018-extract-local-playground.md) |
| SDK 适配边界与 Client 生命周期 | `python/runtime/claude_sdk.py`、`python/runtime/session_actor.py` |
| 工程要求与决策 | [工程问题与约束清单](doc/specs/engineering-requirements.md)、`doc/ADR/` |
| MCP 凭据与配置 | `python/runtime/mcp_auth.py`、`python/runtime/config.py` |
| Client 与存储 | `python/runtime/session_actor.py`、`run_store.py` |
| SDK 会话与文件 | `python/runtime/session_actor.py`、`python/runtime/file_broker.py` |
| 流程与技能 | `.claude/workflows/`、`.claude/skills/` |
| 数据源与共享查询资产 | [.claude/databases/README.md](.claude/databases/README.md) |
| 数据管理、报告与产品流程 | [数据库管理](doc/specs/data-source-connections.md)、[模板计划](doc/specs/template-batch-data-plan.md)、[产品流程](doc/specs/conversation-reporting-product.md)、[ADR-023](doc/ADR/023-database-scoped-asset-packages.md) |
