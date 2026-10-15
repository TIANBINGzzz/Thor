# Runtime 配置中心设计

状态：2026-10-15 提议，待设计评审；尚未实现。用户已选择独立 MySQL 配置库，Nacos 保留现有职责。

## 目标与当前边界

通用配置发布一次，由各环境 Runtime 外部读取并在安全边界应用；保护正在执行的请求，不把 SDK Client 重建称为原地热更新。

| 当前来源 | 实际读取链路与更新边界 |
| --- | --- |
| `application.yml` 模型 | `runtime_settings.load_model_settings` → `config.MODEL_SETTINGS` / `server.DEFAULT_MODEL`；各进程导入时固定，父进程与新 Worker 可能读到不同版本。 |
| `application.yml` 池 | `server.lifespan` → `WorkerPool`；只在 HTTP 服务启动时读取，目前没有动态调整接口。 |
| `databases.json` | `data_source_keys` 可先读一次，`RunServices.bind` → `Executor` 再读；Executor 内固定一轮，但尚无跨模型、策略和池的共同版本。 |
| `.env` / 容器环境 | 本地 dotenv 在启动/逐轮加载；容器 env-file 在创建时注入，改宿主文件不会刷新运行进程。 |
| Nacos | `ConfigSnapshot` 首次引用时读取，Worker 只使用导出的选定值；文件传输另按批次取快照，读取失败直接拒绝对应操作。 |

## 唯一权威来源与范围

| 配置 | 本次唯一权威来源 |
| --- | --- |
| 默认/可用模型、SDK 模型别名、四项预热池参数 | MySQL 配置版本的 `common.runtime`，可由环境覆盖。 |
| 数据源连接的非秘密参数、查询策略和授权范围 | MySQL 配置版本的 `common.sources` / 环境覆盖；业务口径、SQL、模板仍在既有受控资产。 |
| 数据库账号、密码 | 环境或 Secret Manager 投射的部署环境；配置版本只登记受限的凭据变量名，禁止保存明文值。 |
| 模型端点/密钥、图像服务参数、Office/渲染路径、代理、JWT、HTTP 启动参数 | 本次仍由部署环境提供；更新 env-file 需要重建容器，不承诺运行时轮换。 |
| `fileService`、`campusMcp` | 仍只由 Nacos 提供；不复制进 MySQL，也不改变现有失败与传输快照语义。 |
| 配置库连接、环境标识、轮询间隔、Nacos 启动连接 | 部署引导配置；不得从自己要读取的远端配置中获取。 |

显式选择 `file` 或 `mysql` 后端；`file` 保留当前本地开发方式，`mysql` 不读取本地模型/池/数据源文件补值。生产切换后本地旧字段不再参与覆盖，无双写或隐式回退。

引导环境变量固定为 `CCSDK_CONFIG_BACKEND=file|mysql`（默认 file）、`CCSDK_CONFIG_ENVIRONMENT`、`CCSDK_CONFIG_MYSQL_HOST/PORT/DATABASE/USERNAME/PASSWORD`、`CCSDK_CONFIG_MYSQL_CA_FILE`、`CCSDK_CONFIG_MYSQL_TLS=verify_identity|disabled`（默认校验身份）、`CCSDK_CONFIG_POLL_SECONDS`（默认5）。配置库连接超时5秒、读写超时5秒，文档上限1MiB；相对CA路径以仓库根目录为基准，关闭TLS须显式声明。

纳管文档结构为 `common: {runtime: {models, worker-pool}, sources}` 和 `environments: {环境标识: 覆盖对象}`；models、worker-pool 和 sources 内沿用现有字段名。MySQL业务连接用 `username_env`、`password_env` 替代明文 `username`、`password`，仅允许引用 `CCSDK_SOURCE_<来源大写标识>_USERNAME/PASSWORD`；不接受通用变量插值、连接URL或任意秘密引用。Runtime在内存解析，仅把本轮选中来源交给Worker，不将解析后的值存入RunStore。

## 版本与发布

- 复用 SQLAlchemy/PyMySQL；独立配置库使用 InnoDB。Runtime 账号仅 SELECT，管理命令使用独立写账号；不复用业务数据账号或向 Agent 暴露配置库访问能力。
- 两张表：不可变发布表 `runtime_config_releases(revision, schema_version, document, created_at)`；唯一指针表 `runtime_config_head(id, revision, generation)`。`revision` 为不含秘密的发布标识，`generation` 每次激活递增。
- document 明确包含 `common` 和 `environments`；环境标识由可信启动配置固定，例如 59、57、appai。字典逐层覆盖，列表整体替换；缺少所选环境、未知字段、类型错误或空必填值均拒绝，不使用空值表达删除。
- 发布命令完整校验公共配置和全部环境的合并结果，校验模型映射、池约束、来源/表/查询登记、权限范围、连接类型/TLS和策略版本绑定；数据库凭据只校验引用格式，Runtime 再核验该环境实际秘密。
- 发布表写入与 head 更新在同一事务中完成；激活通过 expected generation 比较并交换，避免并发发布覆盖。回滚只把 head 指向已保存版本并递增 generation，不修改旧版本。
- CLI 提供建表、校验、发布、状态和激活已有版本；不新增配置管理网页，不启动自动发布或生产配置迁移。管理操作不打印 document、连接串、SQL参数或秘密。

## Runtime 加载与失败

- 单 HTTP worker 在 lifespan 启动时读取并验证完整候选快照，首版不可用则启动失败；此时不开池、不接业务请求。
- 后台每 5 秒轮询 head（可由启动参数调整，至少 1 秒），发现 generation 变化后用一次一致性查询读取指针及不可变版本；网络操作在线程执行，设置连接/读取超时及响应大小上限。
- 解析、环境合并、秘密引用解析和完整语义校验全部成功后，才在事件循环同步发布不可变快照引用；消费者不得修改共享对象。失败仅更新安全错误码和观测时间，继续使用本进程上一有效版本；不写包含秘密的磁盘缓存。
- 持续不可达仍保留最后有效版本并暴露 stale/最后成功时间；这不是即时权限撤销机制。紧急撤销使用现有取消或外部授权控制，不能以配置轮询代替 Java/下游授权。
- 每个 Run 在装配及入队前领取一次快照，模型、数据源选择、策略与连接由该副本统一提供；排队期间继续使用入队版本，同会话下一 Run 获取当时版本。Worker 仅接收选定来源和所需运行字段，不连接配置库，不重新读本地数据库文件。
- RunStore 只保存 revision、generation、环境标识；进程日志及受鉴权私有状态返回当前版本、最后检查/成功时间和错误码，不导出配置内容或秘密哈希。

## 分类生效方式

| 变更 | 应用方式 |
| --- | --- |
| 默认/可用模型 | 新 Run 固定新选择；持久 Client 仅在 READY、同一所有者 Task 内调用公开 `set_model`。已运行的请求保持原模型。 |
| SDK 模型别名、SDK环境或不可热更的执行选项 | 纳入固定配置指纹；同会话下一轮在 Actor 串行区重建 Client，并恢复已保存 SDK 历史。更新失败使该轮失败，不重跑外部副作用。 |
| 数据库策略/连接 | 新 Run 使用新 Executor；同 Run 的查询、分页和凭据保持旧副本，连接每次使用 NullPool 并及时释放。动态SQL的来源/策略版本必须一致；改配置不自动证明数据库权限已变更。 |
| 池容量/内存阈值 | 在既有池内调整，保留 leased 计数；缩容只回收未绑定空闲库存及超额创建任务，已预留目录保留到领取时校验，已绑定 Client 继续执行。降低 max-live 后阻止新增直到降到上限以下。 |
| 池的 SDK 固定配置 | 新建库存使用新指纹；旧库存领取时不匹配则淘汰冷启，旧版本创建任务完成时不得进入新库存；预留目录不因更新而删除已绑定会话数据。 |
| Token / Nacos业务节点 | 保持既有逐 Run 绑定、结束清理及 Nacos 独立快照；Token 不入配置库、不修改全局环境、不随 Client 跨 Run 保留。 |

SDK 0.2.143 的公开 API 没有通用 options/env 重载及 `set_mcp_servers`；现有 MCP 更新依赖项目集中适配的私有协议，升级继续要求真实 CLI 验证。配置中心不会扩大 SDK 原地更新能力。

主模型始终通过显式 `options.model` / `set_model` 指定，避免默认模型同时注入 `ANTHROPIC_MODEL` 导致修改默认值误触发固定配置重建；SDK模型别名仍进入环境和固定指纹。运行测试须核验这一调整的真实CLI行为。

## 上线与验收

- 初次上线须分别准备配置库权限、各环境引导配置与数据库秘密，导入完整版本后排空并重建容器；后续本次纳管的非秘密参数可通过发布更新。部署引导/秘密轮换仍按其独立流程操作。
- 本地验证覆盖真实 MySQL 事务/CAS/回滚（使用隔离测试库）、无效版本/断网保留旧版、更新时并发请求与排队版本、池缩容及创建竞态、模型切换与固定配置重建、凭据不串用/不落盘；运行 `npm test` 和部署配置回归。
- 缺少隔离 MySQL 测试连接时明确报告未验证项，不用 SQLite 或 Mock 通过代替 MySQL 验收；三环境生效还须逐环境检查观测版本，并执行真实模型/只读问数验证，healthy 不代表已应用。

## 工程要求检查

| 要求 | 状态 | 依据与差距 |
| --- | --- | --- |
| REQ-001 | 部分满足 | 设计保留选定MCP的逐Run凭据绑定，配置库不保存业务Token；实现回归、Java真实透传与运行中撤销尚未验收。 |
| REQ-002 | 部分满足 | 配置版本只由可信服务端装配，不增加前端执行配置入口，Run记录采用版本；实现、Java ACL和生产隔离尚未验收。 |
