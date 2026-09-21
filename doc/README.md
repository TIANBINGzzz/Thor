# 文档入口

每类规则保留一个维护入口；实现细节看代码和测试，业务知识随执行资产维护。

| 内容 | 入口 |
| --- | --- |
| 启动、依赖与部署 | [项目 README](../README.md)、[部署](../deploy/README.md) |
| 系统边界、目录与生命周期 | [架构](../ARCHITECTURE.md) |
| HTTP/SSE、鉴权、文件协议 | [Runtime 契约](specs/ccsdk-runtime-interface.md)、[API HTML 浏览版](python-api.html) |
| Java 职责及消息映射 | [Java 接入](specs/java-control-plane.md) |
| 能力输入与模板约定 | [能力 payload](specs/capability-payload.md) |
| 数据库配置与授权 | [数据库管理](specs/data-source-connections.md) |
| 查询口径与文稿规则 | [数据库资产](../.claude/databases/README.md)、[撰写规则](../.claude/workflows/writing-docx/instructions.md) |
| 持续约束与重要取舍 | [工程要求](specs/engineering-requirements.md)、[ADR 索引](ADR/README.md) |
| 报告业务来源核验 | [原 SQL 核验](verification/report-source-audit.md)、[逐页来源](verification/szpt-midterm-page-sources.md) |
| 有日期的实测记录 | [容量压测](reports/loadtest-2026-09-18.md)、[撰写性能](reports/writing-performance-2026-09-18.md)、[图表压力测试](chart-stress-report-20260921.md) |

接口变化同步 Runtime 契约、HTML 示例和协议测试；只有职责或映射变化才更新 Java 文档。实测记录只证明注明版本和场景，不作为当前部署状态。已退役设计从 Git 历史查阅，不另存归档副本。

## HTML 发布

公网：[Python API 文档](https://cp.stringedu.com/ccsdkscribe/python-api.html)。按服务器配置设置 `CCSDK_DOCS_RELEASE_SCRIPT`（远端脚本）和 `CCSDK_DOCS_INCOMING_DIRECTORY`（上传目录），或传参数 `-RemoteReleaseScript`、`-RemoteIncomingDirectory`。两者须为规范 POSIX 路径，仅允许字母、数字、下划线、点、连字符和路径分隔符。

在项目根目录运行：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\publish-docs.ps1
```

脚本只提交 HTML 的本地修改，上传确定的 Git 版本，原子切换并校验公网 SHA-256；不执行 git push，也不提交其他已暂存文件。回滚加 `-RollbackRelease <发布输出中的 Previous>`，普通更新不需要重载 Nginx。

运维配置由相邻 SSHCloudServer 项目的 `deploy/ccsdkscribe-docs/` 维护；脚本只依赖 Windows Git、OpenSSH 和 curl。
