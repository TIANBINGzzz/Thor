# ADR-012: Java 控制面与 Provider-neutral Agent Runtime

日期: 2026-08-28
决策状态: 已替代
实现状态: 不适用
替代: ADR-013、ADR-014
被替代: 无

## 背景

当前 Python 通过 `claude-agent-sdk` 执行 Agent，Java `ChatServiceImpl` 直接调用 Dify。两条链路各自持有 SSE、会话和 provider ID；未来还需要接入 DeepSeek harness 或其他厂商。当前 Python 的本地会话、文件目录和进程内运行表不能承担生产多租户控制面。

## 决策

1. Java 保留身份、租户、权限、业务会话/消息、文件授权、审计和对浏览器的统一 SSE。
2. Python 保留为薄的 Claude Runtime，负责 SDK/MCP/Skill 配置编译、工具执行和事件翻译；Java 不直接嵌入 Claude SDK。
3. Dify、Claude、DeepSeek 等通过 `AgentRuntimeAdapter` 接入，使用版本化的 `agent-run/v1` 与 `agent-events/v1`；provider session 只保存为不透明引用。
4. Workflow、Skill 和普通会话分别用 `workflowRef`、`skillRefs` 和无 workflow 的 conversation 表达；凭据只以短期、限定 audience/scope 的 grant 引用传递。
5. workflow 与普通会话只有在同一 Runtime 且配置兼容时才允许 resume，否则通过 Java 摘要和产物引用迁移上下文。

## 后果

### 好处

- 前端和业务会话不绑定 Dify 或 Claude，新增 harness 只需增加 Adapter。
- Token、文件路径、工具原始参数和 provider session 可以留在受控 Runtime/审计边界内。
- 可统一处理取消、事件重放、用量和多租户授权。

### 代价

- Java 需要新增 Adapter、Run/Event 持久化和能力注册；Python 需要稳定的内部 HTTP/SSE 协议。
- 不同 provider 的 resume、workflow 和工具能力不能被强行抽象，需返回 capability mismatch。

### 风险

- 在容器/沙箱、文件授权和短期凭据完成前，现有 `bypassPermissions` 与本地目录方案只能用于内部验证。
- 直接复用不兼容配置的 Claude session 可能造成策略或工具上下文泄漏，默认采用 `new_with_summary`。
