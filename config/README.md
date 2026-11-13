# 部署配置

MySQL 是可编辑配置的唯一来源。启动 YAML 只保存配置库引导与宿主机参数；不再读取 Nacos、env、.local 或本地客户配置副本。

| 位置 | 内容 | 更新生效时点 |
| --- | --- | --- |
| `application.yml` | `config-database` 地址、账号、密码、Fernet 根密钥、TLS CA、超时；server/tools/network/diagnostics | 重启 |
| `scribe_capability` | 名称、说明、启停、提示词、附件策略、模型连接/模型名、thinking/effort、全部单 Run 预算、Tool 选择、能力配置 | 下一 Run，包括已有会话续聊 |
| `scribe_skill` | 可复用说明、正文、文本资源及依赖 Tool | 下一 Run |
| `scribe_model_connection` | 服务地址、Anthropic 协议、API Key、协议扩展参数 | 下一 Run |
| `scribe_database_connection` | 类型、地址、端口、库名、账号、密码、TLS、访问范围、查询限额 | 下一 Run |
| `scribe_mcp_server` | HTTP 地址、静态 Header、业务 Token 注入规则、连接参数 | 下一 Run |
| 三张 `scribe_capability_*` 关联表 | Skill 顺序/必载、数据源必需性、MCP 及工具白名单 | 下一 Run |
| `scribe_setting` | images、fileService、security、runtime 全局设置 | 图像/文件与逐轮读取项下一 Run；执行/观测鉴权密钥、Worker 池、观测存储及 HTTP 入口常量重启 |

启动从 config/application.yml 连接配置库，校验后加载进程设置。每个新 Run 在线读取一次一致配置，执行中保持不变；不轮询、不广播、不维护配置版本或发布表。数据库不可达时新请求失败，已经取得配置的 Run 继续执行。普通业务请求不能覆盖配置。

从 [application.example.yml](application.example.yml) 或 [application.production.yml](application.production.yml) 准备完整私有启动文件；三个启动文件字段及类型一致。真实文件与加密根密钥不提交、不进镜像。配置库自身的连接凭据不能存入待连接的库，根密钥也不与密文同库。API Key、数据库密码、静态 MCP Header 和 setting 秘密字段加密存入 MySQL，管理读取不返回原值，PUT 中 null 表示保留。

配置管理 API、表关系和预算语义见 [配置中心契约](../doc/specs/runtime-config-center.md)。表定义以 [config_store.py](../python/runtime/config_store.py) 为准；运行进程不自动建表。新环境由运维通过该 metadata 建表并写入完整配置，不存在默认业务配置回退。schema、模板、工具实现和数据库知识仍随可信代码交付；测试夹具仅用于离线测试，不参与部署配置读取。

数据库 `access.tenantIds` 默认只允许 `self`，每轮从 Java 已认证后透传的业务 Token 解析；额外测试范围遵循 [REQ-001](../doc/specs/engineering-requirements.md#req-001业务-token-透传与按-mcp-注入)。发现连接不授予能力或数据权限，TLS 显式配置，不自动降级。业务数据库 CA/SQLite 相对路径以 config 目录为基准，配置库 CA 同样按 config 目录解析。

模型连接当前只支持 SDK 所需的 Anthropic 协议；兼容该协议的服务可切换地址与密钥。每能力明确指定模型名，不另维护 model_profile 或模型 available 列表。thinking/effort 是否被供应商接受由其协议决定。图像模型属于 images 设置。

Worker 仅接收当轮模型、预算、所需数据库和 MCP 配置，不接收配置库密码、根密钥及控制面 JWT 密钥；SDK 环境不接收数据库秘密。Run JWT、管理 JWT、观测 JWT 和业务 Token 各自独立。可信 Worker 不构成生产 OS 沙箱。
