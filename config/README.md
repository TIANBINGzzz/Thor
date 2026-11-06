# 部署配置

一个 tenantId 对应一个客户，一套 Runtime 只服务一个客户；同客户不同 usercode 可查询客户全量业务数据，用户会话、文件、Run 和结果引用仍分别隔离。

| 配置位置 | 职责 |
| --- | --- |
| `.env` / `.env.local` / 容器 `runtime.env` | Nacos 地址、命名空间、分组、Data ID、只读账号及代理、工具位置等进程参数 |
| [application.yml](application.yml) | 仅 Nacos 连接引导和读取配置中心的网络预算 |
| Nacos `ai-center-agent-service` | 客户 tenantId、模型/JWT/数据库凭据、服务地址及完整 runtime 运行参数 |
| [本地 Nacos 示例](nacos-ai-center-agent-service.yaml) | 带逐项中文注释的占位配置，编辑后发布到 Nacos；不是运行时本地回退文件 |
| `.claude/databases/` | 已登记来源、表列、函数、业务口径和指标；不含连接凭据 |

配置按启动依赖和部署环境划分：[本机 env 示例](../.env.local.example)只放连接 Nacos 前必须具备的地址/账号，以及代理、工具位置、端口和持久化路径。这些值绑定宿主机、容器或启动方式，变更通常需要重建进程；客户和运行策略统一在 Nacos 维护，当前同样须排空重启生效。

| 放置位置 | 选择依据与例子 |
| --- | --- |
| env / Nacos 引导 YAML | 连接配置中心之前就要知道，或依赖宿主机：Nacos 地址/账号、代理、工具路径、端口、Run 库路径 |
| Nacos | 随客户或运维策略调整：tenantId、模型及 JWT 密钥、数据库/业务服务、运行预算、模型映射、池与观测 |
| 代码与执行资产 | 需要验证和发布的规则：协议、Tool Schema、能力权限映射、SQL 口径与表列、模板；不开放为任意 Nacos 字段 |

旧 env 字段迁移对应：ANTHROPIC_BASE_URL/AUTH_TOKEN → model.baseUrl/apiKey；CCSDK_IMAGE_* → images；CCSDK_RUNTIME_JWT_* / CCSDK_OBSERVATION_JWT_SECRET → security。现有 `.env.local` 的 NO_PROXY 继续保留为本机网络配置；真实客户值不写入示例。

## 加载与更新

从仓库根目录运行 `npm start`，或通过 `deploy/entrypoint.py` 启动；自定义 ASGI 启动使用 `PYTHONPATH=python uvicorn --factory runtime.bootstrap:create_app`。初始化必须先于 server、SDK 和预算模块导入。

正式启动只读取一次 Nacos；校验客户配置及完整 `runtime` 参数，不与本地 YAML 合并，不以本地默认值补缺。读取、认证或校验失败直接拒绝启动，不回退旧 env、数据库 JSON 或示例地址。修改配置须排空任务并重启 Runtime，不需要重建镜像；本次不提供热更新。

Nacos 连接默认读取本目录 `application.yml` 的 `nacos`，`application.local.yml` 仅覆盖本机 Nacos 引导；其中旧的 runtime 节点不生效。`.env.local` 覆盖 `.env`，实际进程环境优先；仅白名单引导项生效。`CCSDK_NACOS_NAMESPACE` 填 Namespace ID，空值为 public，Data ID 默认不带扩展名。Nacos 读取本身的 timeout-ms/request-timeout-ms 属于启动引导，必须在取得远端配置之前生效，不在远端 runtime 重复配置。

同一启动快照用于父进程、Worker、文件服务和 MCP 地址装配。Worker 只接收模型、数据库和运行预算，以及本轮明确选择的连接引用，不接收 Nacos/Run JWT/管理 JWT/观测 JWT 密钥；SDK 环境只接收模型和必要进程参数。可信 Worker 和普通 Agent 不构成生产 OS 沙箱。

## 客户字段

完整字段与简短描述以示例为准。`deployment.tenantId` 必须与 Java Run JWT 的 tenant 一致，禁止通配符、self 和 default。数据库调用若收到业务 JWT，其 tenantId 也必须一致；该解码仅作一致性检查，不替代 Java 验签、有效期和撤销控制。

`security.runtimeJwtSecret` 用于执行授权；`observationJwtSecret`、`assetJwtSecret` 可省略以关闭对应接口，配置时必须各不相同。模型的 baseUrl/apiKey 和图像服务的 baseUrl/apiKey/model 分别显式配置，不推导端点或自动共用密钥。

`databases.<source>.connection` 只保存 driver、host、port、database、username、password、tls；`query` 只保存 timeout_seconds、max_rows、dynamic_sql_enabled。来源名称须与能力及来源资产登记一致，校双高使用大小写敏感的 schoolDoubleHigh。TLS 默认验证 CA 和主机名；如环境不支持，须显式设置 disabled，不自动降级。CA 与 SQLite 路径相对仓库 config 目录，绝对路径按部署注入。

数据库不再维护 Capability、模板、租户列表、项目授权或重复表/查询清单。Capability 与模板决定来源选择，Catalog 决定允许的域、表列、函数及指标，SQL AST 对每张物理表强制绑定当前部署客户；项目是业务筛选条件。详见[数据契约](../doc/specs/data-source-connections.md)。

`fileService` 管理平台附件下载和成果上传，downloadPath 保留 `{fileId}`；可选 timeoutSeconds 为 1–3600 秒，maxFileBytes 为 1 字节–10 GiB，下载还受 Runtime 上限约束。显式独立下载 Broker 使用 Nacos fileBroker；不作为默认文件服务失败后的回退。`campusMcp` 只保存校园连接及域名，业务 Token 按 Run 绑定，不保存共享账号 Token。

## Runtime 与观测

runtime 的预算、模型、池及观测配置必须完整写在 Nacos；缺项或非法值拒绝启动。毫秒超时按阶段分别计时，执行预算从附件准备完成后开始。模型 available 限制请求可选值，default 及 SDK 别名均须在 available 中。worker-pool 设置空闲预热、同时启动、存活上限及最低可用内存，不代表生产并发容量已验收。

runtime.observability 控制有界待采日志，默认关闭；storage 相对仓库根目录。观测读取使用独立 JWT，长期存储与游标由采集平台维护。`CCSDK_OBSERVABILITY_ENABLED=0` 保留为进程紧急停采及测试开关；测试不写入本机观测库。连接、真实 Token、原始结果与验证材料只放忽略目录，不进入源码、镜像或 Prompt。
