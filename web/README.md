# Luma Web

Luma 是 Thor 唯一的对话前端，使用 React 和标准 Next.js App Router 构建。页面组件、样式和布局来自远程 Thor Web，运行时功能由根目录的本地 Node Agent 服务提供。

主要功能包括真实 SSE 流式对话、会话历史、按 ID 路由、文件上传与预览、`@` 引用、模型选择、Markdown、Skills/Subagents/工具事件，以及实际 token/费用统计。

浏览器只访问 Next.js 的同源 API routes；这些 routes 使用进程内密钥转发到 `app/server.mjs`。会话、消息、上传文件和模型产物全部保存在根目录 `.scribe-sessions/`，不依赖外部数据库、对象存储或托管运行时。

## 开发

推荐从仓库根目录一次启动前后端：

```powershell
npm run ui
```

该命令使用生产模式运行 Next.js。需要前端热更新时使用根目录的 `npm run ui:dev`。

单独验证 Web：

```powershell
npm install
npm run build
npm run lint
npm test
```
