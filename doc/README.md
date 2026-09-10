# 文档入口

只把会影响开发决策或跨服务协作的内容放在这里。

| 文档职责 | 入口 | 状态 | 何时更新 | 同步范围 |
| --- | --- | --- | --- | --- |
| 项目边界、目录和生命周期 | [ARCHITECTURE.md](../ARCHITECTURE.md) | 当前架构 | 目录职责、系统边界或运行数据生命周期变化 | 受影响的 README、规范；保持九部分结构 |
| 本地启动、配置、测试 | [README.md](../README.md) | 当前入口 | 启动命令、依赖、通用配置或测试入口变化 | 对应脚本、配置示例和文档链接 |
| Java ↔ Python Runtime 契约 | [Runtime 接口](specs/ccsdk-runtime-interface.md) | 当前契约 | 实际请求、鉴权、响应、事件或文件协议变化 | Java 控制面实现部分、API 页面和相关测试 |
| Java 业务控制面接入 | [Java 控制面](specs/java-control-plane.md) | 推荐设计 + 源码核实的实现 | Java/Python 请求、鉴权、文件、事件、适配边界或前端展示变化；设计被采纳；联调发现差异。纯内部重构不扩写 | 实际协议变化同步 Runtime 规范、API 页面和测试；纯建议只更新设计及差异记录；重要已采纳决策另记 ADR |
| 持续工程约束 | [工程要求](specs/engineering-requirements.md) | 必须持续检查 | 新增或调整要求，或实现证据、差距变化；每次方案变更均须检查 | 受影响的方案、规范及实施总结；已实现要求仍保留 |
| 架构取舍和替代关系 | [ADR 索引](ADR/README.md) | 当前决策 + 历史索引 | 重要决策新增、替代或状态变化 | 对应 ADR、索引、替代链接及受影响的规范 |
| Java 接口 HTML | [python-api.html](python-api.html) | 当前接口浏览入口 | 对外展示的接口契约或示例变化 | 与 Runtime 规范、Java 控制面实现部分核对；发布方式见下文 |

本表统一维护更新条件与同步范围；各文档只保留自身的简短维护约定、更新时间和适用的源码核对基线。

`ADR/` 只记录重要取舍；`archive/` 只保留历史材料，不作为实现依据；`examples/` 已归档，示例不是运行时配置。

## HTML 发布

公网：[Python API 文档](https://cp.stringedu.com/ccsdkscribe/python-api.html)。修改 `doc/python-api.html` 后，在项目根目录运行：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\publish-docs.ps1
```

脚本仅提交该 HTML 的本地修改，上传 Git 中的确定版本，原子切换并校验公网 SHA-256；不会执行代码仓库的 `git push`。其他文件不发布，已有暂存内容不随该提交提交。
回滚：同一命令加 `-RollbackRelease <发布输出中的 Previous>`。历史版本保留在服务器 `releases/`，普通文档更新不需要重新加载 Nginx。
运维配置由相邻 `SSHCloudServer/deploy/ccsdkscribe-docs/` 维护；本项目发布脚本可独立运行，只依赖 Windows Git、OpenSSH 和 curl。

本次静态发布工程要求检查：REQ-001 不适用（无业务 Token/MCP）；REQ-002 不适用（无 Capability/执行资产入口），不改变 Runtime 契约。
