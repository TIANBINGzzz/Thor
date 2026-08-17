# 架构决策记录（ADR）

本目录记录项目的重要架构决策。

## 什么时候写 ADR

- 技术栈选型（MCP vs ORM、容器 vs 沙箱）
- 安全边界设计（权限隔离、认证方式）
- 数据流向和存储方式（引用语法、会话文件）
- 明确放弃某个方案（为什么不用 XX）

## 什么时候不写 ADR

- 实现细节（某个函数怎么写）
- 临时决策（先这样，以后再改）
- 能从代码推导的事实（目录结构、依赖版本）

## 当前决策

| 编号 | 标题 | 状态 |
|------|------|------|
| [001](001-no-backward-compatibility.md) | 不保留向后兼容 | 已采纳 |
| [002](002-mcp-for-database.md) | 使用 MCP 动态挂载数据库 | 已采纳 |
| [003](003-container-isolation-for-security.md) | 使用容器隔离工作目录 | 提议 |
| [004](004-reference-syntax-for-large-datasets.md) | 引用语法处理大候选集 | 已采纳 |

## 模板

使用 [template.md](template.md) 创建新的 ADR。
