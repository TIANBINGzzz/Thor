# CCSDKScribe

基于 Claude Agent SDK 的本地 Agent 与对话应用。通过 Anthropic 兼容接口调用 Qwen，加载 Claude Code 工具、Skills、Subagents 和 Commands，并通过 MCP 接入数据库。

## 快速开始

```bash
# 配置环境变量
cp .env.example .env
# 编辑 .env，填入 ANTHROPIC_AUTH_TOKEN、ANTHROPIC_BASE_URL、ANTHROPIC_MODEL

# 对话界面
npm run ui

# 命令行问答
npm start -- "分析这个项目当前具备哪些能力"

# 专业报告
npm start -- "/report 为管理层撰写本项目技术能力与上线风险报告"

# 数据库演示
npm run db:demo -- "查询员工表字段，并统计员工人数"

# 测试
npm test
```

## 项目结构

```text
CCSDKScribe/
├── app/                    # 应用代码
│   ├── index.mjs          # CLI 入口
│   ├── server.mjs         # HTTP + SSE 服务
│   ├── agent-options.mjs  # Agent 配置
│   ├── database.mjs       # 动态挂载 MCP
│   └── *.test.mjs         # 单元测试
├── .claude/               # Claude 配置
│   ├── skills/            # 数据分析、RAG、报告写作
│   ├── agents/            # 研究员、分析师、撰稿人
│   ├── workflows/         # 多代理编排
│   └── commands/          # /report 命令
├── web/                   # Next.js 前端
├── docs/ADR/              # 架构决策记录
├── CLAUDE.md              # 项目指令
└── backlog.md             # 已知问题与待办
```

## 配置

### Qwen（百炼）

```dotenv
ANTHROPIC_AUTH_TOKEN=你的百炼_API_KEY
ANTHROPIC_BASE_URL=https://你的_WORKSPACE_ID.cn-beijing.maas.aliyuncs.com/apps/anthropic
ANTHROPIC_MODEL=qwen3.7-max
```

### Qwen（Coding Plan）

```dotenv
ANTHROPIC_AUTH_TOKEN=你的_CODING_PLAN_KEY
ANTHROPIC_BASE_URL=https://coding.dashscope.aliyuncs.com/apps/anthropic
ANTHROPIC_MODEL=qwen3.7-plus
```

### 数据库

```dotenv
# PostgreSQL
DATABASE_URL=postgres://USER:PASSWORD@HOST:5432/DATABASE?sslmode=require

# MySQL
DATABASE_URL=mysql://USER:PASSWORD@HOST:3306/DATABASE

# SQLite（Windows 绝对路径）
DATABASE_URL=sqlite:///D:/path/to/database.db
```

### WebFetch 代理

`claude.exe` 不读 Windows 系统代理，需要配置环境变量：

```dotenv
HTTPS_PROXY=http://127.0.0.1:7897
HTTP_PROXY=http://127.0.0.1:7897
NO_PROXY=localhost,127.0.0.1,.aliyuncs.com
```

`NO_PROXY` 必须排除百炼网关（`.aliyuncs.com`）。

## 已知限制

- **WebSearch 不可用**：当前 Qwen 兼容网关会伪造成功但不执行搜索。已通过 `disallowedTools` 禁用。
- **权限隔离未实现**：当前启用 `bypassPermissions`，模型可以读写任意文件和执行命令。生产部署前必须实现容器隔离（见 `docs/ADR/003`）。
- **环境变量优先级**：`.env` 使用 `override: true`，因为 cc-switch 等工具会向系统环境注入 `ANTHROPIC_BASE_URL`。

## 架构决策

重要决策记录在 `docs/ADR/`：

- [001-no-backward-compatibility.md](docs/ADR/001-no-backward-compatibility.md)
- [002-mcp-for-database.md](docs/ADR/002-mcp-for-database.md)
- [003-container-isolation-for-security.md](docs/ADR/003-container-isolation-for-security.md)
- [004-reference-syntax-for-large-datasets.md](docs/ADR/004-reference-syntax-for-large-datasets.md)

## 技术栈

- **Agent**: `@anthropic-ai/claude-agent-sdk@0.3.231`
- **数据库**: `@bytebase/dbhub@1.2.0`
- **前端**: Next.js + `@assistant-ui/react`
- **运行时**: Node.js 22+, TypeScript 5.9

## 后续计划

详见 `backlog.md`：

1. 容器隔离与权限控制
2. 工具审批 UI 与 `canUseTool` 集成
3. 使用 `Query.interrupt()` 实现可控停止
4. 会话索引恢复与审计日志
5. 多租户隔离（tenantId、工作目录、MCP 实例）
6. 接入独立搜索 MCP
7. 报告质量评测

## 许可

MIT

## 前端主题与对话框调整（2026-08-17）

- 对话框桌面宽度统一为 780px，最小高度 132px，底部安全距离 30px；文本区、工具栏和发送按钮采用参考页的 54px / 34px / 36px 比例。
- 主题切换按钮与参考页保持一致，采用 36px 图标按钮、毛玻璃背景、边框阴影和月亮/太阳图标切换，主题保存在 `thor-theme`。
- 移动端保持工具栏单行布局，模型选择器限制在 150px 内，并将主题按钮移到对话框上方，避免遮挡。
- Agent 服务暂不可用时，侧栏、模型和引用数据使用空数组兜底，页面仍可加载空白对话界面。

### 下一步执行计划

1. 启动 Agent 服务后，验证真实会话列表、模型切换和文件上传在新尺寸下的交互。
2. 在浅色、深色、窄屏和键盘导航场景下补充截图回归。
3. 完成会话选中态、快捷任务入口和错误提示的视觉统一。

## 当前前端状态

- Web 前端以 Next.js + `@assistant-ui/react` 为运行时基础，保留现有 Agent、SSE、文件、引用和 Skills 能力。
- `@assistant-ui/react` 只负责 Thread、Message、Composer、流式状态和自动滚动；按钮、主题、布局、文件预览和弹层视觉仍由本地 HTML/CSS 控制。
- 当前没有引入完整 UI 框架；模型菜单、引用选择器和文件预览先保持本地实现，待复杂交互边界稳定后再评估 Base UI 是否只用于 Popover/Dialog 等行为层。
- 工作区默认使用深色主题，右下角按钮以月亮表示深色、太阳表示浅色；主题选择保存在浏览器本地，并在页面水合前应用以避免刷新闪烁。
- 历史会话侧栏使用克制的中性背景标识当前会话，不叠加强调线、时间强调或额外阴影。
- 统计页直接展示服务端返回的实际费用、token、回复和会话数据，不显示预估或账单说明文案。

## 后续计划

1. 完善主题令牌在统计页、文件面板和引用菜单中的一致性。
2. 补齐主题首次加载、刷新恢复与历史会话选中态的桌面及移动端视觉回归测试。
3. 为 Web 交互增加会话选择和 SSE 流式更新的回归测试。

## Frontend interaction update (2026-08-17)

- Removed the composer mouse-position React state and radial hover overlay so pointer movement no longer rerenders the conversation tree or causes message flicker.
- Added GPT-style history actions: a hover/focus-visible three-dot menu with rename and delete actions, inline rename with Enter/Escape support, and delete confirmation backed by the existing session PATCH/DELETE APIs. Menu and rename state live in the isolated history-list component, while rail paint containment keeps hover animation repaints out of the conversation workspace.
- Kept the history action affordance visible on narrow/mobile layouts where hover is unavailable.

### Next frontend checks

1. Verify history menu keyboard navigation and focus return after rename/delete.
2. Add browser regression coverage for composer hover stability and session actions.
3. Recheck history popup placement when the sidebar is collapsed or opened as a mobile drawer.

## Model selector update (2026-08-17)

- Increased the composer model label to 14px and strengthened its weight for faster scanning.
- Reworked the model popover into a 300px selection panel with model capability labels, stable selection marks, larger hit targets, and responsive mobile sizing.
- Added menu keyboard behavior for Arrow Up/Down, Home/End, Enter, and Escape while preserving click and outside-click handling.

## Writing skill update (2026-08-17)

- Added `.claude/skills/writing-documents/SKILL.md` for long-form document and DOCX workflows, including evidence collection, outline confirmation, template preservation, manuscript revision, consistency review, and final DOCX acceptance.
- Kept the existing `report-writing` skill unchanged; use `writing-documents` for broader document/DOCX tasks and `report-writing` for decision-ready research reports.

### Next skill checks

1. Test the skill on a new long-form report and a template-based DOCX revision.
2. Verify DOCX rendering and structure checks with the available document tooling.
