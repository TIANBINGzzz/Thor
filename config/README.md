# 部署配置

一个 tenantId 对应一个客户，一套 Runtime 只服务一个客户；不同 usercode 可查询客户全量业务数据，会话、文件、Run 和结果仍按用户隔离。

| 配置组 | 本机真实文件 | 字段范例 | 生产模板 |
| --- | --- | --- | --- |
| 启动及宿主机 | `application.yml` | [application.example.yml](application.example.yml) | [application.production.yml](application.production.yml) |
| Nacos 客户配置 | `nacos-ai-center-agent-service.yml` | [nacos-ai-center-agent-service.example.yml](nacos-ai-center-agent-service.example.yml) | [nacos-ai-center-agent-service.production.yml](nacos-ai-center-agent-service.production.yml) |

每组的三个版本字段路径和类型保持一致，每项带简短注释；本机文件保存真实值，不提交 Git、不进入 Docker 上下文。example 和 production 只有模板值，生产须逐项填写；未替换的 replace-*、customer-example 和 example.com 地址会拒绝启动。可选字段保留，按注释用空字符串或 enabled 关闭，不删除节点。

| 放置位置 | 职责与选择依据 |
| --- | --- |
| application.yml | 连接 Nacos 前必需，或绑定宿主机：Nacos 引导、监听地址/端口、Run 库、OfficeCLI/渲染器、代理、诊断 |
| Nacos ai-center-agent-service | 模型及图像服务、JWT 密钥、数据库和业务服务地址、完整 runtime 预算/模型/池/观测 |
| .claude/ 与代码 | 需验证发布的 Capability、Tool Schema、权限映射、数据库表列/口径及模板，不开放为任意配置 |

## 加载与更新

从仓库根目录执行 npm start 或 python python/server.py；自定义 ASGI 启动使用 PYTHONPATH=python uvicorn --factory runtime.bootstrap:create_app。启动只读 config/application.yml，再从 Nacos 读取一次客户配置，校验并冻结快照；初始化必须先于 server、SDK 和预算模块导入。

不加载 .env、capability.env 或 .local 覆盖，不用应用环境变量覆盖 YAML，不合并本机与生产文件，不回退本地客户 YAML。Nacos 本地三版本只供填写及导入，不是运行时配置来源。缺字段、错类型、重复 YAML 键、读取或认证失败均拒绝启动。配置变更须排空任务并重启，不需要重建镜像。

Nacos namespace 填 Namespace ID，空值为 public；读取超时只在 application.nacos 配置，Nacos 始终直连。network 的空代理会清除继承代理。工具和 Run 库路径仅支持操作系统目录变量 ${LOCALAPPDATA}、${USERPROFILE}、${PROGRAMFILES}；密钥不展开变量。SDK/工具仍通过进程环境接收启动器装配的值，这不是 env 配置文件。

生产将填写后的完整 application.production.yml 只读挂载为 /app/config/application.yml；客户 production 内容另行导入 Nacos。挂载、权限及容器路径见[部署说明](../deploy/README.md)。

## 客户字段与隔离

Run、用户及会话身份来自已验证的 Java Run JWT，不在部署配置固定 tenantId。数据库访问的 self 每轮解析 credentials.platformBearer 中的业务 tenantId；缺少业务 Token 或解析失败即拒绝，不回退测试 ID。本地解码不替代 Java 验签、有效期或撤销。

security.runtimeJwtSecret 用于执行授权；observationJwtSecret、assetJwtSecret 留空关闭对应接口，配置时三种密钥必须独立。model 与 images 的连接和密钥显式配置；供应商允许共用模型密钥时，可用 YAML 锚点 &model_api_key 和 *model_api_key 表达，不隐式复用。images.enabled=false 不装配图片工具，仍保留其全部字段。

databases.<source>.connection 只保存 driver、host、port、database、username、password、tls；query 只保存超时、行数与动态只读 SQL 开关。校双高来源名称为大小写敏感的 schoolDoubleHigh。TLS 验证 CA 和主机名，不支持时须显式 disabled，不自动降级；CA 和 SQLite 相对路径基准为仓库 config 目录。

每来源 access.tenantIds 声明数据租户范围：production 和 example 模板仅 [self]；额外测试数据须按[工程要求 REQ-001](../doc/specs/engineering-requirements.md#req-001业务-token-透传与按-mcp-注入)明确授权，具体环境例外保存在私有部署交接记录。额外 ID 不改变 Run 身份，不影响其他来源或校园大脑。数据库不重复维护 Capability、模板、项目授权或表/查询清单；Catalog 决定域、表列、函数及指标，每个学校 scope 单独绑定 SQL 租户过滤，项目只是业务筛选条件。详见[数据契约](../doc/specs/data-source-connections.md)。

fileService 是附件下载和成果上传的唯一文件通道，downloadPath 保留 {fileId}；不转发 Run JWT、业务 Token 或 Cookie，Java 须先授权 fileId。旧 Java File Broker 通道及配置已删除。campusMcp、businessMcp 只保存可信连接，业务 Token 按 Run 注入；businessMcp.url 留空不挂载。

runtime 的预算、模型、池及观测字段必须完整；default 和 SDK 别名须在 available 中。观测 storage 相对仓库根目录；启动 YAML diagnostics.disable-observability=true 用于紧急停采，false 仍以 Nacos 开关为准。

父进程及 Worker 共享启动快照；Worker 只接收模型、数据库、运行预算和本轮选定连接，不接收 Nacos、执行/管理/观测 JWT 密钥；SDK 不接收数据库凭据。真实 Token、原始结果及私密验证材料只放忽略目录。可信 Worker 不构成生产 OS 沙箱。
