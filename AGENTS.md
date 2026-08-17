# Agents 定义

本文件记录项目中定义的子代理及其职责划分。

## 约束

1. **不要在此文件重复 CLAUDE.md 的内容**。架构约束、工作方式、技术约定见 `CLAUDE.md`。
2. **不要编造或臆测代理能力**。只记录 `.claude/agents/*.md` 中实际定义的代理。
3. **保持简洁**。每个代理只写：名称、职责、典型使用场景。
4. **同步更新**。新增或删除代理时必须同步更新此文件。

## 当前代理

### researcher（研究员）
- **职责**：收集和整理项目相关的事实信息
- **场景**：需要梳理代码库、文档、配置时使用
- **定义**：`.claude/agents/researcher.md`

### data-analyst（数据分析师）
- **职责**：执行数据查询、统计分析和数据验证
- **场景**：需要访问数据库、计算指标、验证数据时使用
- **定义**：`.claude/agents/data-analyst.md`

### writer（撰稿人）
- **职责**：撰写专业报告、技术文档和结构化输出
- **场景**：需要产出管理层报告、技术方案时使用
- **定义**：`.claude/agents/writer.md`

## 使用方式

子代理通过以下方式调用：

```javascript
// 在 workflow 中
const research = await agent("梳理项目架构", { agentType: "researcher" });
const data = await agent("统计用户数", { agentType: "data-analyst" });
const report = await agent("撰写技术报告", { agentType: "writer" });
```

或通过 Command 触发（如 `/report` 会自动编排这些代理）。

## 架构约束

所有代理遵循 `CLAUDE.md` 中的开发约束和工作方式。具体规则见该文件。
