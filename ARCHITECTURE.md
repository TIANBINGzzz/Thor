# ARCHITECTURE.md

仅维护以下九部分：目的、上下文、代码地图、职责、依赖、不变量、边界、横切关注点和查找入口；不展开接口字段、操作教程或待办。生产目标不代表已完成验收。

## 1. System purpose

CCSDKScribe 是供 Java 调用的 Python Claude Agent SDK Runtime，支持对话、Workflow/Skill、MCP、文件处理和流式事件。

## 2. System context

```text
本地：独立 ScribePlayground -> Python Runtime -> SDK -> 模型 / MCP
生产目标：业务前端 -> Java 控制面 -> Python Runtime -> SDK -> 模型 / MCP
                                └-> Dify 适配器（外部执行后端）
```

Java、ScribePlayground 及其业务存储均不在本仓库；两者通过相同 Runtime HTTP 契约接入。

## 3. Top-level codemap

```text
python/       后端与 SDK 执行
  runtime/    协议、鉴权、配置、Run、Actor
  tools/      DOCX、Artifact 工具
  tests/      后端测试
.claude/      skills/、agents/、commands/、workflows/ 执行资产
doc/         specs/ 规范、ADR/ 决策、静态 API HTML
```

## 4. Subsystem responsibilities

- Java 控制面：业务身份、租户、资源 ACL、Capability、会话/文件和审计。
- `python/server.py`：Java HTTP/SSE 与 Run 调度；`runtime/`：执行配置、状态、存储与生命周期。
- `python/agent_worker.py`：调用 SDK、消费消息并向父 Runtime 上送事件；`tools/`：具体工具实现。
- `.claude/workflows/<name>/`：流程 profile、约束、语义和专属配置。
- 外部 `ScribePlayground`：测试页面、模拟 Java 的会话/上传/File Broker 与测试 JWT 签发，不包含 SDK 执行。

## 5. Dependency directions

调用方向：入口 → Runtime → SDK Worker → 模型 / MCP；Runtime 配置层加载执行资产并装配工具。
核心运行时不依赖 Web 展示；流程专属知识留在 Workflow 目录，不写入通用 Python 代码。业务授权来自 Java，模型与工具不得反向提升权限。

## 6. Architectural invariants

- 生产前端只触发已授权 Capability；Workflow、Skill、Agent 是内部组成，不接受前端任意执行配置。
- 业务 Token、Run JWT、模型密钥用途分离；业务 Token 仅按规则注入选定 MCP，不进入模型输入或持久化。
- 业务会话、Run、SDK session、Client 和浏览器连接生命周期分离；断开 SSE 不等于取消 Run。
- 公共事件统一脱敏，凭据和执行状态不得跨用户/租户串用。

这些是必须守住的要求；Capability 解耦等现存差距见工程要求清单，不能把目标当作已实现。

## 7. Important boundaries/interfaces

- Java ↔ Python：内部 Run 协议、Run JWT、状态/事件及取消；完整字段见 Runtime 规范。
- RunStore 内部记录与 HTTP 响应分离；身份用于 Python 归属校验，SDK Session 与执行元数据不返回 Java。
- Run 身份仅取自已验证 Run JWT 的 `tenant`、`sub`；请求正文不重复声明身份，业务 MCP Token 不作为身份来源。
- 父 Runtime ↔ Worker：JSONL 进程边界；独立执行使用 `query()`，持久执行由 SessionActor 独占 Client。
- Python ↔ MCP：受控服务器配置和按 MCP 注入的凭据；规则不由浏览器或模型提供。
- 业务文件 ↔ Runtime 工作目录：通过授权引用获取输入；本地路径不能替代文件 ACL。

## 8. Cross-cutting concerns

- 安全：当前 `bypassPermissions` 和路径约定不构成生产沙箱；多租户需文件、进程、网络及凭据隔离。
- 可靠性与观测：Run 状态、事件回放、超时、取消和 Client 恢复分别管理；运行事件通过 RunStore 管理。
- 数据生命周期：`.scribe-runs/` 含运行记录、SDK 会话及工作数据；业务会话、上传由 Java 管理，历史测试 `.scribe-sessions/` 已迁至 ScribePlayground。运行数据不是可整体删除的缓存。
- 临时内容：`.tmp/`、`scratch/` 用于临时验证/笔记，清理前确认无占用和唯一成果；依赖与构建缓存可重建。
- 容量：局部限额不等于磁盘总配额；运行数据仍需保留、归档和清理策略。

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
