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
