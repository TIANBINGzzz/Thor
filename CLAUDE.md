# CCSDKScribe 项目说明

## 项目目标

使用 Claude Agent SDK 通过 Anthropic 兼容接口调用 Qwen，并通过 MCP 扩展数据库、检索、分析和报告撰写能力。

## 开发约束

1. 不保留向后兼容。过时的直接删，别加兼容层、别写 migration、别留 fallback。
2. 选能满足当前需求的最简单实现。不要预防性抽象，不要多此一举的配置层。
3. 系统分层长。先跑通最小端到端版本，再往上加东西。绝不为了未完成的复杂度拆掉能跑的东西。
4. 组件保持模块化，关注点分离。
5. 优先用成熟的、有人维护的库。没有明确理由别自己重写。
6. 先翻项目里已有的依赖能做什么，再考虑加新包或自己写。
7. 架构决策往长了做。不接受"先这样以后再换"的临时方案。
8. 先看成熟产品怎么解决同一个问题，用已验证的模式，别从零发明。

## 文档管理规范

**原则**：尽量不写冗长文档，只做简单记录。

- `FUTURE-IDEAS.not-for-model.md` 是人工后续需求备忘：模型默认跳过，不主动读取或据此实施；仅在用户明确要求查看或维护该备忘时读取。

### ADR（架构决策记录）

所有架构决策记录使用 ADR 格式，放在 `doc/ADR/` 目录：

- **格式**：参考 `doc/ADR/template.md`
- **长度**：20-30 行，不超过 50 行
- **内容**：背景、决策、后果（好处/代价/风险）
- **命名**：`NNN-kebab-case-title.md`

❌ **禁止创建**：
- 超过 100 行的详细教程文档
- 实现细节和完整代码示例文档
- 使用指南、troubleshooting 长文档
- 在 `doc/` 根目录放置冗长 MD 文件

✅ **正确做法**：
- 只有重要架构决策才写 ADR
- 代码即文档，依赖 README 和代码注释
- 临时笔记用 scratch/ 目录，不提交 Git

### 结构与方案检查

- 阅读代码前先看 `ARCHITECTURE.md`；目录职责、系统边界或运行数据生命周期变化时同步更新。
- 每次新增或修改方案，必须逐条检查 `doc/specs/engineering-requirements.md`，在方案与实施总结中列出要求编号、满足状态、依据和差距；不适用也须说明原因。
- 工程要求持续保留，不因实现完成而删除；未满足或与既有规范冲突时必须显式指出，不能以当前代码为由静默弱化要求。

## 技术约定

- Runtime HTTP/SSE、Run、SDK 会话、文件获取和 Agent 子进程使用 Python；HTTP 层采用 FastAPI，Agent 执行使用 `claude-agent-sdk`
- Runtime 代码放在 `python/`，执行资产放在 `.claude/`；测试 UI 和模拟 Java 控制面位于独立项目 `../ScribePlayground`，只能通过 HTTP 契约连接，禁止 Runtime 导入测试项目。Node.js 只用于 DBHub 等 MCP 和项目脚本。
- 可复用的大规模多代理编排使用 `.claude/workflows/*.js`；单 Agent 的确定性 workflow 使用同名目录中的 `workflow.json` 声明 `execution.mode=direct`，由 Python 直接启动受限 SDK Run，不再经过 Skill/Workflow/子代理
- `python/` 放应用后端、Agent SDK worker 和可复用运行时方法；workflow 专属表范围、数据库名和 provider 模板不得放入 Python 目录
- workflow 专属环境变量放在同名目录被忽略的 `workflow.env`；通用密钥放在根 `.env` 或 Secret Manager，不得写入代码、Skills、Agents、日志或报告
- workflow 的约束和语义 Markdown 必须在 `workflow.json` 的 `documents` 清单中显式登记；未登记的文件不会进入 prompt
- `database-qa` 的语义来源维护在 DBProcessing 的 `doc/model_context`，接入时只提炼硬约束、业务口径和必要字段；`not_for_model` 中的 DDL、样例值、真实 ID 和人工快照只作人工核验，不注入 prompt
- `database-qa` 默认是国双高口径：项目/资金/绩效按有效项目标记，纯任务统计按任务标记；标记不一致必须披露，不能静默用另一种标记排除数据
- 真实问数验证必须使用临时进程环境和只读 SQL，对照独立基准；不得把真实凭据、租户值、内部 ID 或结果明细写入仓库
- 架构决策写入 `doc/ADR/`，实现细节写代码注释，项目结构变化同步更新 `README.md`

## 当前安全状态

当前入口启用了 `bypassPermissions` 和完整 Claude Code 工具预设。模型可以读写文件并执行命令，不适合直接用于生产或多租户环境。正式部署前必须加入租户级工作目录、会话、凭证、MCP 和数据库权限隔离，以及审计与人工确认策略。
