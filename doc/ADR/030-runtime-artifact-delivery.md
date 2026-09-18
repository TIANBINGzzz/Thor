# ADR-030: Runtime自动上传及按ID交付文件

| 字段 | 内容 |
| --- | --- |
| 决策日期 | 2026-09-18 |
| 决策状态 | 已采纳 |
| 实现状态 | Python已实现，Java与前端待接入 |
| 替代的旧 ADR | 无；替换Runtime旧文件名下载契约 |
| 被哪份 ADR 替代 | 无 |

## 背景

共享会话目录按文件名列出成果会混淆Run与历史版本。模型文本中的链接不能证明文件已上传，也不能作为业务授权依据。

## 决策

- 发布工具创建artifactId及不可变文件快照，父Runtime绑定当前可信Run；上传地址与Header由databases.json顶层fileService提供。
- Runtime用httpx流式multipart上传现有接口，成功确认的data.id作为fileId；data.url只作内部存储路径，不推测下载URL。
- 文件状态与事件原子持久化，公开pending/uploading/ready/failed/unknown；仅ready可关联远端文件，模型工具仅返回pending。
- SDK结束后等待已提交上传收尾，再发Run终态；文件失败不伪造SDK失败。重启仅恢复pending，发送结果不确定不自动重试。
- Java按Run/message及artifactId关联fileId并做ACL，前端从结构化事件渲染卡片；本次只改Python和契约，未实施Java/前端。
- 按ID提供列表、详情及本地快照内容；删除?name下载方式，不保留兼容层。
- POST重传复用现有Run JWT的run.execute及新jti，不新增scope，仅重用明确失败的原快照；保留artifactId，不重跑模型或改变Run终态，Java用单文件GET查询结果。unknown拒绝重传，正在上传和ready不重复发送。

## 后果与验收

- 同名文件支持多版本，长SSE按页回放；模型回答无需遵循文件链接格式。
- 快照和原始工作文件额外占磁盘，尚需保留/清理策略；现有文件服务无租户ACL、幂等键和对账API，unknown需人工核对。
- 配置不会主动进入Prompt或公开事件，但bypassPermissions不是生产文件/凭据沙箱；不得宣称已完成多租户安全验收。
- 测试覆盖multipart、事件顺序、超时、恢复、同名版本、HTTP鉴权、重传防重放/并发去重/快照完整性及跨Run拒绝，见test_artifact_delivery/runtime与test_runtime_http。
- 2026-09-18：真实文件服务接收59字节合成文本并返回fileId，状态依次pending/uploading/ready；尚未验证远端下载接口或完整报告的Java/前端链路。

## 工程要求检查

| 要求 | 状态 | 依据与差距 |
| --- | --- | --- |
| REQ-001 | 部分满足 | 上传不接收Run JWT或业务Token，公共事件使用白名单；现有Java凭据链路及进程隔离差距保留 |
| REQ-002 | 部分满足 | 上传目标与Run归属来自可信配置/执行上下文，重传复用Run JWT执行权限及防重放，不触发模型；Java文件ACL及前端卡片仍待联调 |
