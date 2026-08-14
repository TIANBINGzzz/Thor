# Thor

Thor 是一个基于 Claude Agent SDK 的 AI Agent 与对话应用实验项目。模型服务通过 Anthropic Messages API 兼容接口接入，目前使用 Qwen 配置进行开发和连通性测试。

## 项目组成

- 根目录：TypeScript Agent SDK 运行器，开放 Claude Code 常用工具并加载本地 Skills。
- `web/`：Luma 极简 AI 对话前端，基于 React、vinext 和 Cloudflare Sites。

Luma 目前支持：

- 模型选择与文本/多模态标识
- 独立会话、历史记录及 `/chat/:session_id` 路由
- 基于 `session_id` 的消息与文件隔离
- 文件上传、预览与下载，单文件最大 10 MB
- Cloudflare D1 消息存储与 R2 文件存储
- 独立用量统计页面，仅展示实际返回的 token 与费用
- 桌面端和移动端响应式布局

当前网页端的会话、文件和界面流程已经可用，但助手回复仍为模拟流式输出，尚未连接根目录的 Agent SDK。完成接入后才会产生真实模型回复、token 和费用数据。

## 本地运行

要求 Node.js 22 或更高版本。

### Agent SDK

复制 `.env.example` 为 `.env`，填写 Anthropic 兼容接口地址、令牌和模型名称：

```powershell
npm install
npm run check
npm run agent -- "检查当前项目结构"
```

Agent 默认允许 `Read`、`Write`、`Edit`、`Glob`、`Grep`、`Bash`、`WebSearch`、`WebFetch`、`Task` 等常用工具，并加载 `.claude/skills/` 下的项目 Skills。

### Luma Web

```powershell
cd web
npm install
npm run dev
```

生产构建：

```powershell
npm run build
```

## 当前模型

- `deepseek-v4-flash`：纯文本
- `deepseek-v4-pro`：纯文本
- `qwen3.8-max`：多模态
- `qwen3.7-plus`：多模态

请勿提交 `.env` 或任何真实访问令牌。
