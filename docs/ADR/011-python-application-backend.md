# ADR-011: 应用后端统一使用 Python

日期: 2026-08-26
决策状态: 已采纳
实现状态: 已实现
替代: 无
被替代: 无

## 背景

项目原先由 Node 提供 HTTP/SSE、会话、文件和引用服务，再通过 JSONL 启动 Python Agent worker，造成同一条请求链存在两套后端语言、两套测试和重复的进程生命周期处理。
前端仍依赖 Next.js，数据库 MCP 当前仍依赖 DBHub，因此不能完全移除 Node 运行时。

## 决策

应用后端统一迁移到 Python FastAPI，包括认证、HTTP/SSE、会话、文件、引用、统计和启动编排。
Agent 继续运行在独立 Python worker 中，通过 JSONL 隔离 SDK 与 Web 服务进程。
保持现有前端 API、SSE 事件、`.session.json` 和历史会话格式兼容。
Node.js 只保留给 Next.js 前端、DBHub 和尚未迁移的 Node 项目脚本。

## 后果

### 好处
- 后端配置、进程回收和测试集中在 Python
- 不再维护 Node 到 Python 的应用桥接层
- 前端无需修改现有 API 和流式协议

### 代价
- 本地完整界面仍需同时安装 Python 和 Node.js
- Next.js 与 DBHub 的进程仍由 Python 启动器编排

### 风险
- SSE 断线仍会取消当前 worker；刷新后续订、多实例运行锁和事件恢复仍需外部状态存储
