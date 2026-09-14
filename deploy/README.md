# 云效部署（内网 Linux Docker 单实例）

这是待目标环境验证的内网试运行配置，不代表生产已验收。ACK 或裸机 Python 需要不同部署步骤。
[配置迁移问题与真实流程验证](checks/README.md) 记录 localhost、代理、路径、密钥注入及实测缺陷。
云效通过界面配置下面的任务；本仓库不提供未经云效校验的专用 YAML。

## 流水线

| 阶段 | 配置 |
| --- | --- |
| 拉取代码 | 选择已连接的 Codeup 仓库与分支；现有过滤发布脚本会保留部署文件 |
| 构建、测试、推送 | Linux Docker 构建机；镜像仓库服务连接先登录 ACR；设置 `CCSDK_IMAGE=仓库地址/命名空间/ccsdkscribe:完整提交SHA`，执行 `sh deploy/build.sh` |
| 部署制品 | 将本提交的 `deploy/` 目录作为流水线制品传至目标内网服务器；构建阶段不读取部署密钥 |
| 主机部署 | 主机组或内网自建 Runner；同一 `CCSDK_IMAGE` 传入主机任务；执行 `sh deploy/deploy.sh`；目标机需具备镜像拉取权限 |
| 验收 | 在可信调用方验证 JWT、SSE、取消、会话续接；按需验证真实模型、数据库及附件/DOCX |

流水线阶段名称以云效当前界面为准。云效组织、仓库连接、ACR 服务连接、主机组须在实际账号中配置。
构建机和主机应使用相同 CPU 架构；都需要 Docker，主机需要 Compose >=2.30（raw env_file）和 `flock`。部署前必须设置 `CCSDK_CONFIG_DIRECTORY`，指向跨版本保留的主机配置目录；相对路径以 `deploy/` 为基准。不同发布目录部署同一服务必须使用同一配置目录，默认锁文件为该目录下的 `deploy.lock`；可用 `CCSDK_DEPLOY_LOCK_FILE` 指定共同锁文件。
镜像内包含 Python、SDK/CLI 和 Node/DBHub；开启保密变量生成 env 时，部署主机另需 Python 3（只用标准库），无需安装应用依赖或 Node。
Docker Hub 不通时可设置 `NODE_IMAGE`、`PYTHON_IMAGE` 为组织 ACR 中同步的对应 Debian Bookworm 官方镜像（建议固定 digest）；不要替换为来源不明的镜像。

## 保密变量与客户换 Key

- 云效将 `ANTHROPIC_AUTH_TOKEN`、`CCSDK_RUNTIME_JWT_SECRET`、可选 `DB_PASSWORD` / `CCSDK_FILE_BROKER_SERVICE_TOKEN` 设为保密变量；模型 URL、模型名、issuer/audience 等为普通配置。DB_HOST/DB_USER 也可设为保密变量。变量名与 `write-env.py` 一致，值不用手动加引号。
- 在内网部署任务的进程环境中绑定这些变量，设置 `CCSDK_GENERATE_ENV=1`、可选 `CCSDK_WITH_DATABASE=1`，执行 `sh deploy/deploy.sh`。不要把变量值直接拼接进 shell 脚本、命令参数或流水线 YAML；不要启用 `set -x`。远程主机任务是否自动透传变量必须在云效实测，不能把构建机环境等同于服务器环境。
- 脚本在 `CCSDK_CONFIG_DIRECTORY` 生成 `runtime.env`（0600）及可选 `database-qa.env`（UID/GID 10001、0400），目录 0700；问数模式需 root 设置属主。单独运行 `write-env.py` 时可传 `--directory`（相对当前工作目录），优先于该环境变量；两者都未设置则报错。生成文件不作为构建制品上传。Workflow dotenv 中的 `${...}` 值会拒绝生成，避免被运行时插值改写。
- 内网服务器不必是 ECS；云效需有可达的主机组或自建 Runner。Runner 要能访问 Codeup、制品/镜像仓库和目标 Docker；完全离线客户用导出的镜像包和现场配置。
- 客户修改 Key：有云效就修改对应保密变量并重新部署；无云效就由客户管理员修改主机 `runtime.env`，执行 `CCSDK_GENERATE_ENV=0 CCSDK_PULL_IMAGE=0 CCSDK_IMAGE=已导入镜像 sh deploy/deploy.sh`。不要把新 Key 作为命令行参数。更换供应商时同时核对 BASE_URL、MODEL 及默认模型配置。
- 部署脚本强制重建容器以刷新环境。仅 `docker restart` 不会加载更新后的 env_file；先排空正在执行的任务，换 Key 后做真实模型调用，确认成功再撤销旧 Key。当前没有凭据热更新或自动回滚。
- 不在镜像里保存 Key，不用 `docker commit` 制作含密钥镜像；镜像层会随镜像分发。`docker exec` 中 export 只影响新 shell，不会更新正在运行的服务。Docker 管理员仍能查看容器环境，保密变量不是对主机管理员的加密隔离。

## 配置与数据

- 运维将 `runtime.env.example` 的实际配置放到 `CCSDK_CONFIG_DIRECTORY` 下的 `runtime.env`；目录限制访问，文件权限 `0600`，由有 Docker 权限的部署账号读取。密钥也可由 Secret Manager 生成。使用已有文件时可分别设置 `CCSDK_ENV_FILE`、`CCSDK_DATABASE_ENV_FILE`；启用自动生成时统一使用配置目录内的新文件。
- 通用配置通过容器环境注入；不要上传本机 `.env`，不要用构建参数传密钥，不要运行会展开密钥的 `docker compose config`（脚本只用 `--quiet`）。`runtime.env` 是 raw 格式，值不加外层引号，`$` 原样传入。
- 问数另备同目录的 `database-qa.env`，内容按 Workflow 的 `workflow.env.example`，只读挂载。文件需允许容器 UID 10001 读取，例如属主 10001、权限 `0400`；设置 `CCSDK_WITH_DATABASE=1` 启用。此文件由 python-dotenv 解析，不使用 Compose raw 语法。
- 问数当前 Workflow 的库名是 `test_hpm_dev`；上线前须在受控 Workflow 配置中确认库名、表白名单和只读账号，不能只改密码。数据库端权限才是最终约束。
- `.dockerignore` 排除密钥和本机数据；代码不需要根 `.env` 也能从环境读取配置。现有本地 dotenv 覆盖行为不变。
- 固定命名卷 `ccsdkscribe-runtime-data` 保存 Run、工作文件及 SDK 配置/会话；升级保留该卷。制定卷的备份、保留期限和磁盘告警；不要执行 `down -v`。仅改数据库文件路径不足以持久化全部状态。
- 默认只在主机 `127.0.0.1:4310` 暴露。Java 跨主机访问时设 `CCSDK_BIND_IP` 为 ECS 私网 IP，并限制安全组来源；网关开启 TLS、关闭 SSE 缓冲并放宽流式超时。File Broker mTLS 证书另加只读挂载，配置填写容器内路径。

## 发布限制与回滚

- 保持一个副本、一个 HTTP worker；4 GiB/2 CPU 只是初始资源限制，并非容量承诺。容器非 root、移除 capabilities 不能替代租户沙箱，模型仍可执行命令并访问容器内同用户文件。
- 发布前让调用方停止接收新 Run，等活动任务结束再部署。当前没有自动排空及无损滚动升级，替换容器会中断尚未完成的任务。
- 回滚时将 `CCSDK_IMAGE` 改为已留存的上一版本 tag/digest，重新执行部署脚本；保留同一数据卷。数据库格式兼容和配置变更要单独核对，镜像回滚不等于业务副作用回滚。
- HTTP 健康检查仅证明服务可响应；构建成功不证明模型、数据库、JWT 签发和 File Broker 已连通。
- 2026-09-11：现有 Node 锁文件审计报告 4 项 moderate（`hono`、`qs` 及依赖链）。目前 DBHub 走 stdio，但仍需修复并验证，不因镜像可构建而宣称生产安全。
- 2026-09-11 修复版验证：Windows 与 Linux 各 90 项测试通过；真实配置注入后并发对话、SSE、取消、DBHub SELECT 1、DOCX 生成下载和同会话修改通过。附件因未接入 File Broker 失败，业务问数租户隔离和 DOCX 内容/版式仍未验收；云效及 ECS 未部署验收。

## 离线镜像导入

真实流程修复版导出为 `dist/ccsdkscribe-20260911-live-linux-amd64.tar`，使用 `docker load -i ccsdkscribe-20260911-live-linux-amd64.tar` 导入；镜像名为 `ccsdkscribe:20260911-live`。旧 `20260911` 镜像存在 Client 缺陷，不再用于部署。
导入后准备上述主机配置，在 `deploy/` 执行 `CCSDK_IMAGE=ccsdkscribe:20260911-live docker compose up -d --wait`；问数加 `-f compose.yaml -f compose.database.yaml`。
离线导入不执行 `deploy.sh` 的仓库拉取步骤；不要把镜像 tar 提交到 Git。后续发布使用提交 SHA 或 digest 标识镜像。

## 本次工程要求检查

| 要求编号 | 状态 | 依据 | 差距与后续处理 |
| --- | --- | --- | --- |
| REQ-001 | 部分满足 | 构建排除密钥；Workflow 凭据独立挂载；不改 MCP 选择性注入 | Java 真实透传、Token 撤销、跨租户执行隔离仍需端到端验收 |
| REQ-002 | 部分满足 | 原 HTTP 契约、Capability 映射和执行资产保留在 Runtime 镜像 | Java 业务授权、配置版本审计及生产接入仍需验收 |
