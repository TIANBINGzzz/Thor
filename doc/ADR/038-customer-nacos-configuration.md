# ADR-038: 单客户 Runtime 配置归入 Nacos

| 字段 | 内容 |
| --- | --- |
| 决策日期 | 2026-11-06 |
| 决策状态 | 已采纳 |
| 实现状态 | Python 与部署资产已接入；本地回归，生产 Java 与发布待验收 |
| 替代的旧 ADR | [ADR-028](028-bundled-database-config.md)的数据库打包交付 |
| 被哪份 ADR 替代 | 无 |

## 背景

用户确认 tenantId 对应客户，一客户一套 Runtime、数据库和服务地址；不同 usercode 共享客户全量业务数据。现有 env、YAML 和数据库 JSON 的职责交叠，重复授权清单增加交付成本。

## 决策

- 按用户进一步确认，删除 env 与 .local 配置覆盖；application.yml 完整保存 Nacos 引导及宿主机参数；启动与 Nacos 两组均保留本机、example、production 三版，字段路径/类型一致，可选项用空值或开关表达。本机真实文件不提交、不进镜像；生产只读挂载完整 YAML。Nacos 是数据源范围、秘密、地址及完整 runtime 参数的唯一来源。启动读取、校验并冻结，缺项或失败不回退本地值，修改后排空重启。
- 数据库按 connection/access/query 拆分；access.tenantIds 的 self 逐轮从业务 Token 解析，生产模板默认仅 self，测试租户的环境例外遵循[REQ-001](../specs/engineering-requirements.md#req-001业务-token-透传与按-mcp-注入)。移除数据库 JSON 打包、selected 项目授权和重复 Capability/模板/表/查询清单，SQL 边界从 Catalog 派生。
- 删除全局 deployment.tenantId；Run JWT 的 tenant/sub 只绑定执行、会话、文件与结果归属。数据库必须携带业务 Token 解析 self，缺失或非法不回退额外测试租户。固定和动态 SQL 均保留 AST 客户过滤、绑定参数及只读事务；用户会话、文件、结果与 Run 控制仍隔离。
- 双高只在数据层读取本轮业务 tenantId，不将 Token 交给模型或数据库驱动；校园 MCP 仍按轮绑定当前业务凭据。Worker 不接收控制面密钥，SDK 不接收数据库秘密。

## 后果与验收边界

同一镜像可部署不同客户，不需要改源码连接；example/production 逐项注释且只有模板值；本机值只保存在私有 YAML，导入 Nacos 后生效。当前不提供热更新、在线来源上传或完整配置发布版本；旧 Git/镜像历史仍保留原数据库版本，移除当前文件不等于历史擦除。

REQ-001部分满足：Python逐轮注入和秘密边界保留，Java Token 来源及撤销未端到端验收。REQ-002部分满足：来源仍由可信能力和模板装配，SQL绑定客户；Java ACL、完整审计及OS隔离仍有差距。
