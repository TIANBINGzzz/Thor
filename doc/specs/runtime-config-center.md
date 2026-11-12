# 配置管理：当前实现与目标方案

2026-11-12：按 `python-sdk` 代码静态核对，Java 与业务前端在外部项目，本次未验证其实现。本文整理需求和待实施方案，不修改运行协议或部署；当前配置仍按 [配置说明](../../config/README.md) 和 [ADR-038](../ADR/038-customer-nacos-configuration.md) 执行。

## 当前实现

业务链路为：前端选择 Capability → Java 授权 → Python HTTP/Run 调度 → Worker 内 SDK Agent loop → Tool/Operation → 数据库、MCP 或文件服务 → SSE 与成果引用。详细职责见[架构地图](../../ARCHITECTURE.md)。

| 部分 | 已实现内容与代码入口 |
| --- | --- |
| 能力与提示词 | `.claude/` 保存源码资产；[capabilities.py](../../python/runtime/capabilities.py) 按文件签名缓存目录，[prompt_assembly.py](../../python/runtime/prompt_assembly.py) 统一装配与预览；必载/按需 Skill 显式登记 |
| Tool 与业务代码 | [tool_catalog.py](../../python/runtime/tool_catalog.py) 按引用读取声明；[tool_registry.py](../../python/runtime/tool_registry.py) 固定登记可信 Provider；校园业务 Operation 在 `python/capability_packs/campus-brain-query/`，其余能力复用声明式资产和通用工具 |
| 数据与连接 | `.claude/databases/` 管语义和查询；[bootstrap.py](../../python/runtime/bootstrap.py) 先读启动 YAML，再由 [deployment_config.py](../../python/runtime/deployment_config.py) 读取、校验并冻结 Nacos 连接、秘密和预算；修改后排空重启 |
| 管理接口 | [asset_management.py](../../python/runtime/asset_management.py) 支持目录、校验、预览和新建能力；仅组合已登记资产，不提供共享资产、连接或密钥的编辑接口 |
| 持久化 | 新建能力及创建记录原子写入 `.scribe-runs/capabilities/`，不覆盖已有能力；[RunStore](../../python/runtime/run_store.py) 用 SQLite 保存执行状态与事件，业务消息由 Java 管理 |

`config.py` 已保存本轮部分装配内容和摘要，但不是完整发布版本。当前没有 MySQL 配置管理、凭据加密库、通用资产编辑/发布/回滚链路，也没有通用 Workflow/DAG 引擎；`direct` 不保证模型调用顺序或必定调用某个工具。

## 需求与边界

- 服务强业务场景：从平台创建、修改并复用 Capability、公共提示词、Skill、Tool、数据源、连接、凭据及运行预算；能力通过引用组合这些对象。持续约束见 [REQ-003](engineering-requirements.md#req-003平台统一配置管理)。
- 保留 Agent loop；可复用方法归 Skill，确定性业务动作归 Operation。必须由系统保证的顺序另行设计受控执行入口，本次不引入可视化 DAG 或通用插件框架。
- 可配置的是已支持的行为：本地 Tool 的接口须匹配实现，HTTP MCP 可登记连接并发现操作，stdio MCP 仍依赖已部署程序；Provider、业务代码、Skill 脚本及依赖随部署交付。
- 数据源连接、语义和使用范围一起管理，但连接成功不代表口径已验证，也不自动授予能力访问权；`pending`、`blocked`、`needs_definition` 保持原含义。

## 目标存储与职责

| 对象 | 权威存储与管理方式 |
| --- | --- |
| 提示词、Skill 正文及业务知识 | Java 管理的 MySQL，正文用 `MEDIUMTEXT` / `utf8mb4`，业务层限制长度；标识、状态和版本单独存字段，列表不加载全部正文 |
| Capability、Tool、模型与预算、数据源语义及连接参数 | 同一 MySQL；检索字段独立保存，配置主体用 JSON，引用关系由 Python 校验；不为每个字段建立配置表 |
| 数据库密码、模型 API Key、MCP 固定凭据 | MySQL 加密凭据记录，连接只保存凭据引用；同一管理表单完成连接与密码维护，不再要求到 Nacos 配密码 |
| 模板、图片、PDF 等文件 | 现有文件服务，MySQL 保存文件引用与版本；不把大文件装进 JSON 或提示词字段 |
| 代码和初始资产 | 代码继续随 Git 与部署包交付；资产纳管后以平台为准，源码资产只作初始导入或经校验发布的更新来源，不按运行时优先级合并两份可编辑内容 |
| 启动依赖 | 配置库自身连接、加密主密钥、管理链路初始认证及宿主机参数由部署 Secret/启动配置提供，不依赖先读配置库 |

Java 负责管理页面、客户归属与授权、存储、凭据加密和发布记录；Python 负责字段及引用校验、有效提示词预览、连接探测、装配和执行。Python 通过可信内部接口获取已发布内容，不直接依赖 Java 表结构，也不让 Java 复制 Runtime 校验器。

凭据使用成熟库做认证加密（如 AES-GCM），保存必要的密文、随机量和密钥标识；主密钥不与密文同库存放，备份恢复须同时保障外部密钥可用。页面仅录入/替换，不回显原值；执行时按授权解析所选凭据，经受保护内部通道交给实际调用组件，明文不进入 Prompt、导出、版本正文或日志。业务 Token 仍按 Run 透传，不持久化成配置；普通配置回滚不自动恢复旧凭据。

## 发布与生效

1. Java 保存草稿与编辑版本，避免并发覆盖；管理端可列出共享 Prompt、Skill、Tool 和数据源的使用方。
2. Python 校验确切草稿及依赖版本，复用现有提示词编译器预览；连接测试单独触发，普通预览不连数据库、MCP 或模型。
3. 发布记录固定通过校验的内容、引用版本和操作者；依赖或正文改变后重新校验，不能校验一份再发布另一份。
4. Runtime 获取并校验发布内容，成功后切换新 Run 的读取入口，回报实际生效版本；保存、发布和已生效分别显示，加载失败不得宣称成功。
5. Run 从入队起绑定发布版本和依赖集合，执行中不继续追读最新配置；停用与凭据撤销独立处理，不能用版本固定延长已撤销授权。

| 变更 | 首版计划的生效方式 |
| --- | --- |
| 提示词、Skill、模板、数据语义、能力预算 | 新 Run 使用新版本，在途 Run 保留所绑定内容；能力预算受平台上限约束 |
| Tool 组合与 MCP 定义 | 新 Run 重新装配，SDK 固定启动条件变化时重建 Client |
| 连接、固定凭据、全局预算与 Worker 池 | 保存到 MySQL，首版仍排空重启；紧急撤销须停止相关执行并使旧凭据失效 |
| Python 代码、Provider、程序依赖 | 部署生效 |

发布版本只保存配置内容和依赖引用，不复制每个节点、整套源码或业务数据库，也不实现 Git diff。Run 记录发布编号与代码部署版本；Skill/模板需要路径时，Python 将对应资产物化为执行副本并按版本复用，不在每次 Tool 调用时访问管理库。只清理未被排队或运行中的 Run、保留审计和回退版本引用的内容，文件与配置版本按保留策略回收。

## 改造顺序与决策边界

1. 先跑通一个能力的草稿、Python 校验/预览、MySQL 发布、新 Run 执行和回退；保留现有 Agent loop、SSE 与文件交付链路。
2. 扩展到共享 Prompt、Skill、Tool、模板及数据语义；复用现有目录校验和编译器，统一提供本轮发布资产，不重做工具执行层。
3. 建立连接与加密凭据管理，加入预算和模型配置；验证密钥恢复、轮换、客户范围和实际连接，再切换配置来源。
4. 按对象一次性纳管，切换后移除对应 Nacos/本地可编辑来源，不保留双写或回退旧配置的兼容层；补齐 Runtime 生效确认与逐 Run 追溯。

最终目标不再把业务连接、凭据和运行预算分别维护在 Nacos 与 MySQL。当前 [ADR-038](../ADR/038-customer-nacos-configuration.md) 仍描述已实现的 Nacos 方案；本次只登记目标差异，实施切换时再记录替代决策并同步部署契约。当前的一客户一 Runtime、客户数据范围及用户会话隔离不因更换配置存储自动改变。

具体表结构、内部传输字段、缓存刷新方式与保留期限在首条链路中确定，不在此预设公共 Run API 字段或建设独立通用配置平台。

## 工程要求核对

| 编号 | 当前状态 | 依据与差距 |
| --- | --- | --- |
| REQ-001 | 部分满足 | 已有 `mcp_auth.py` 逐轮绑定；新增凭据存储/交付未实现，Java 来源、撤销及日志边界仍需真实验收 |
| REQ-002 | 部分满足 | 已有能力解析、统一预览及 Operation 装配；Java 授权与完整发布版本追溯不能由 Python 静态核对代替 |
| REQ-003 | 部分满足 | 已有受限能力新建与预览；统一编辑、MySQL、加密凭据及发布生效链路均待实施，本文不作为功能验收 |
