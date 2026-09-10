# 文档入口

只把会影响开发决策或跨服务协作的内容放在这里。

| 需要了解 | 入口 | 状态 |
| --- | --- | --- |
| 项目边界、目录和生命周期 | [ARCHITECTURE.md](../ARCHITECTURE.md) | 当前架构 |
| 本地启动、配置、测试 | [README.md](../README.md) | 当前入口 |
| Java ↔ Python Runtime 契约 | [Runtime 接口](specs/ccsdk-runtime-interface.md) | 当前契约 |
| Java 业务控制面接入 | [Java 控制面](specs/java-control-plane.md) | 接入设计 |
| 持续工程约束 | [工程要求](specs/engineering-requirements.md) | 必须持续检查 |
| 架构取舍和替代关系 | [ADR 索引](ADR/README.md) | 当前决策 + 历史索引 |
| Java 接口 HTML | [python-api.html](python-api.html) | 当前接口浏览入口 |

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
