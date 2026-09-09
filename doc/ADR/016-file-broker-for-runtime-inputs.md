# ADR-016: Runtime 输入文件通过 File Broker 获取

| 字段 | 内容 |
| --- | --- |
| 决策日期 | 2026-09-04 |
| 决策状态 | 已采纳 |
| 实现状态 | 部分实现 |
| 最近核对 | 2026-09-07 |
| 替代的旧 ADR | 无 |
| 被哪份 ADR 替代 | 无 |

## 背景

浏览器 attachmentIds 由 Java 映射为 input.attachmentRefs[].fileId；Python 无权访问业务数据库或接收永久 URL、对象存储 key、本地路径。

## 决策

- 固定附件在 Agent 执行前由 Runtime 调用 Java File Broker，以 runId + fileId + purpose 和 Run JWT/mTLS 授权上下文获取文件；属于资源准备，不依赖模型或 MCP。
- 优先代理文件流；现有一次性 URL 兼容模式必须有 expiresAt、oneTime=true、TTL 不超过 5 分钟且只在 Runtime 内存中存在。
- 仅模型需要自主选文件时才考虑绑定当前 Run 的 file-access MCP，并纳入主消息流观测；这不是固定附件路径的前置依赖。
- 不新增浏览器/Java Runtime DTO/公共 SSE 字段；Broker 缺失时带附件 Run 以稳定错误码失败关闭，不猜地址、不查库、不绕过 ACL。
- Broker 重验租户用户、附件归属、会话/消息关联、上传成功、purpose 与 Run 绑定；不能只信请求体身份。代理流和 URL grant 都提供 name、mimeType、size、sha256。
- 下载器限制连接/读取及总超时、大小、摘要、允许 Host 和重定向，原子落盘并在 Run 终态清理；URL 仅 HTTPS:443，全部 DNS 地址须为公网并固定已验证 IP 防重绑定。
- URL、Authorization、本地绝对路径不入日志；私有观测只记录 transferMode 与已验证低敏元数据，供兼容路径退出评估。

## 实现证据与差距

- 代码：[file_broker.py](../../python/runtime/file_broker.py) 已实现代理流/URL 下载校验，[server.py](../../python/server.py) 接入执行前准备、终态清理和失败关闭。
- 验证：[test_file_broker.py](../../python/tests/test_file_broker.py) 的下载、摘要、SSRF、超时及调用顺序检查随本次 Python 测试通过；Broker 使用替身。
- 差距：沿用原 ADR 的 Java File Broker 未闭环结论，本次未核查外部 Java 仓库或实际接口；长期 TTL、跨实例 GC、孤儿目录回收及生产文件链路仍待验收。

## 后果

- 好处：固定输入可预测、可审计，临时凭据不会成为模型选择工具的前提。
- 代价：Java 必须提供有资源授权的 Broker，Runtime 需维护下载校验与工作目录清理。
- 风险：只验证下载地址不等于验证文件 ACL；允许 Host、授权方式或清理错误可能造成泄漏及磁盘积累。

## 工程要求检查

| 要求 | 状态 | 依据 | 差距与后续处理 |
| --- | --- | --- | --- |
| REQ-001 | 不适用 | Broker 使用 Run 授权，不是业务 Token 的 MCP 注入 | 不得据此把 platformBearer 广播到下载端。 |
| REQ-002 | 部分满足 | Python 接收可信附件引用并在准备失败时拒绝执行 | Java 真实文件 ACL、能力授权及配置追溯未验证。 |

## 状态变更记录

| 日期 | 决策状态 | 实现状态 | 说明 |
| --- | --- | --- | --- |
| 2026-09-07 | 已采纳 | 部分实现 | 将自由描述归一为部分实现，补充证据与差距；不表示本日完成开发。 |
