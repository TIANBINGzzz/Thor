# 配置说明

本目录的 [databases.json](databases.json) 保存数据库连接和访问策略；平台文件服务配置由 Nacos 提供。两者仅供服务端读取，不传给模型。

默认读取本目录配置；可用 `CCSDK_DATABASES_FILE` 指定其他文件，相对路径以项目根目录为基准。修改配置后排空任务并重启服务；使用镜像内配置时须重建部署。

本文集中维护配置字段，不复制实际地址、账号、密码或业务租户值。资产职责与查询边界见 [数据契约](../doc/specs/data-source-connections.md)。

## 顶层结构

| 字段 | 用途与约束 |
| --- | --- |
| `version` | 配置文件格式版本，当前读取器要求为整数1；不是数据库或模板的版本。 |
| `sources` | 业务数据源登记表；每个键必须对应.claude/databases下的数据源目录，不能在此表中插入注释条目。 |
| `sources.schoolDoubleHigh` | 校双高业务数据源，hpm为其内部业务域；名称不代表另一套独立数据库。 |

## Nacos 文件服务：fileService

平台文件服务配置：输入附件下载和生成成果上传共用；不属于数据库连接，也不提供业务文件权限判断。

每个环境的 Nacos 创建 `public / DEFAULT_GROUP / ai-center-agent-service`，格式选 YAML，内容以 `fileService:` 为根；Data ID 不加扩展名。可从 Nacos 导出并导入其他环境，再修改该环境的地址。
启动连接统一放在本目录 [application.yml](application.yml) 的 `nacos` 下：`server-addr`（主机:端口或 HTTP(S) URL）、`namespace`（Namespace ID，public 用空字符串）、`group`、`data-id`。固定读取仓库根目录下的 `config/application.yml`，不依赖启动工作目录，随镜像交付。
本机可在同目录创建 `application.local.yml`，只写需要覆盖的 `nacos` 字段，例如 `nacos: {server-addr: nacos-dev.example.internal:8848}`；未写字段继承公共配置。该文件被 Git 和 Docker 忽略，缺少时使用公共配置，存在但无效时明确报错。优先级为环境变量 > 本地文件 > 公共文件，空字符串也是显式覆盖。
`.env` 或部署环境只需配置 `CCSDK_NACOS_USERNAME`、`CCSDK_NACOS_PASSWORD`；YAML 不接收凭据。部署需要时可用 `CCSDK_NACOS_URL`、`CCSDK_NACOS_NAMESPACE`、`CCSDK_NACOS_GROUP`、`CCSDK_NACOS_DATA_ID` 显式覆盖对应字段，环境变量优先（包括空字符串）。容器须使用容器可达的地址。
每批附件下载、每个成果上传开始前通过 Nacos 2.x HTTP API 获取并校验配置；认证与读取共用10秒预算，每个响应分块检查，单次网络阻塞最多5秒，响应上限128 KiB。一次传输及其重试固定使用同一快照。下一次传输读取更新，因此同一 Run 的下载和后续上传可能使用不同版本，切换整套文件存储前应排空任务。
没有本地文件回退或磁盘缓存；未配置、认证失败、不可达或内容无效时文件操作失败，不影响无文件的对话。更改 Nacos 启动参数须重启 Runtime。使用已有 httpx/PyYAML，无需额外 SDK 或 gRPC 端口。

```yaml
fileService:
  baseUrl: https://files.example.internal
  domainName: business.example.internal
  remoteUrl: https://business.example.internal
  downloadPath: /fwk_manage_service/sys_attachment/{fileId}/ai/download/
```

| 字段 | 用途与约束 |
| --- | --- |
| `baseUrl` | 文件服务请求的基础地址，只填协议、主机和可选端口，不带业务路径、查询参数或账号密码。 |
| `domainName` | 请求头domain-name的值，供平台选择业务域；它不是登录Token。 |
| `remoteUrl` | 请求头remote-url的值，供平台路由识别来源；只填HTTP(S)来源地址，不带业务路径。 |
| `downloadPath` | 文件下载GET路径；{fileId}由本轮授权附件引用替换，使用存文件接口返回的data.id，不是模板业务ID或会话附件ID。 |
| `timeoutSeconds` | 默认600，范围1–3600秒；上传的全部尝试和等待共用预算，下载还受Runtime全部附件准备预算约束。 |
| `maxFileBytes` | 默认1 GiB，范围1字节–10 GiB；单文件上传限制，下载与CCSDK_FILE_MAX_BYTES取较小值，不代表磁盘总配额。 |

## 访问策略：sources.schoolDoubleHigh.policy

该数据源的访问策略，限制身份、能力、模板、项目范围及可查询的业务资源。

| 字段 | 用途与约束 |
| --- | --- |
| `tenant_id` | 允许使用来源的Runtime租户ID；*表示显式允许所有调用租户共用此来源，不表示业务数据按调用租户隔离。 |
| `business_tenant_id` | 业务库中的租户/学校过滤值，由运行时注入声明了该参数的固定查询；与Run JWT中的调用租户身份区分。 |
| `revision` | 授权策略版本，修改权限或范围时递增；启用动态SQL时必须同步核验并更新connection.scope_policy_revision。 |
| `users` | 允许访问的用户ID数组，或all_authenticated表示所有已认证用户；不是允许匿名访问。 |
| `capabilities` | 允许使用该来源的业务Capability标识，还须通过数据源资产中的能力登记；不是Workflow或工具名称。 |
| `templates` | 使用预制templateKey时允许访问来源的模板标识；仅为授权白名单，不负责登记或启用模板，上传附件不靠此列表识别。 |
| `project_scope` | 业务项目访问范围配置，与报告年度、国双高筛选等查询口径区分。 |
| `project_scope.mode` | all_school允许全校项目范围；selected只允许同级project_ids数组指定的项目。全校权限不取消查询自身的业务筛选。 |
| `dynamic_sql_enabled` | 是否允许受控只读SQL；true仍须满足数据库侧范围约束、来源/策略版本绑定、表列白名单和SQL校验。 |
| `domains` | 按业务域分别授权查询和表；域名须已登记在对应数据库资产包。 |
| `domains.hpm` | 项目、建设任务、资金及绩效业务域。指标口径和关联规则维护在对应数据库资产包。 |
| `domains.hpm.queries` | 允许调用的固定查询ID白名单；定义和SQL在.claude/databases/schoolDoubleHigh/metrics/hpm，列入白名单不会把待定义或受阻查询变成可执行查询。 |
| `domains.hpm.tables` | 允许查询的物理表白名单，必须存在于该业务域已登记的schema；不是授权访问整库，也不允许写入。 |

## 数据库连接：sources.schoolDoubleHigh.connection

实际数据库连接参数及数据库侧权限约束声明；仅由运行时读取，不注入模型提示词。

| 字段 | 用途与约束 |
| --- | --- |
| `tenant_id` | 允许使用此物理连接的Runtime租户ID；*允许共享连接，必须与policy.tenant_id分别校验。 |
| `driver` | SQLAlchemy驱动名；mysql+pymysql通过PyMySQL连接MySQL，sqlite用于已存在的本地数据库文件。 |
| `host` | 数据库服务器主机名或IP，不是文件服务器或Java业务服务地址。 |
| `port` | 数据库TCP端口，MySQL常用3306；以实际部署为准。 |
| `database` | MySQL物理库名；SQLite场景为数据库文件路径，相对路径以此配置文件目录为基准。 |
| `tls` | 数据库连接的TLS设置，只作用于数据库，不影响平台文件服务的HTTP(S)连接。 |
| `tls.mode` | disabled关闭数据库TLS；verify_identity启用证书及主机名校验，此时须同时配置tls.ca_file和tls.verify_identity=true，CA相对路径以本配置文件目录为基准。 |
| `revision` | 物理连接配置版本，变更连接或数据库侧约束时递增，用于追溯查询实际使用的连接。 |
| `timeout_seconds` | 数据库连接、读写等待及查询执行的秒级预算，运行时限制为1至120秒；不是整个模型Run的超时。 |
| `max_rows` | 一次查询物化结果的最大行数，运行时限制为1至100000；超出上限标记结果不完整，不能当作完整统计。 |
| `database_scope_enforced` | 部署方声明数据库账号/视图已限制到完整授权范围；设置true不会自动创建数据库权限，也不能靠模型SQL的WHERE代替隔离。动态SQL要求该值为true。 |
| `username` | 数据库登录账号，使用具备所需只读及范围限制的账号；不是业务系统登录用户名。 |
| `password` | 上述数据库账号的密码；当前按项目授权随私有配置和镜像交付，不得写入日志、提示词或公开文档。 |
| `scope_source_key` | 数据库侧范围约束所对应的数据源标识；执行动态SQL时必须与实际source_key一致。 |
| `scope_policy_revision` | 数据库侧范围约束所对应的授权策略版本，必须等于policy.revision；修改权限后须重新核验数据库约束，不能只机械更新数字。 |
