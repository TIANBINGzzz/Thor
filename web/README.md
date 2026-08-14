# Luma Web

Luma 是 Thor 项目的极简 AI 对话前端，使用 React、vinext 和 Cloudflare Sites 构建。

主要功能包括会话历史、按 ID 路由、消息与文件隔离、文件上传与预览、模型选择，以及实际 token/费用统计。数据通过 Cloudflare D1 保存，文件通过 R2 保存。

当前助手回复仍为模拟流式输出，尚未接入根目录的 Claude Agent SDK。

## 开发

```powershell
npm install
npm run dev
```

```powershell
npm run build
npm test
```

部署配置位于 `.openai/hosting.json`。
