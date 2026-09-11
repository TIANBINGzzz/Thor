# 云效部署（ECS / Linux Docker 单实例）

这是待目标环境验证的内网试运行配置，不代表生产已验收。ACK 或裸机 Python 需要不同部署步骤。
云效通过界面配置下面的任务；本仓库不提供未经云效校验的专用 YAML。

## 流水线

| 阶段 | 配置 |
| --- | --- |
| 拉取代码 | 选择已连接的 Codeup 仓库与分支；现有过滤发布脚本会保留部署文件 |
| 构建、测试、推送 | Linux Docker 构建机；镜像仓库服务连接先登录 ACR；设置 `CCSDK_IMAGE=仓库地址/命名空间/ccsdkscribe:完整提交SHA`，执行 `sh deploy/build.sh` |
| 部署制品 | 将本提交的 `deploy/` 目录作为流水线制品传至目标 ECS；构建阶段不读取部署密钥 |
| 主机部署 | 同一 `CCSDK_IMAGE` 传入主机任务；执行 `sh deploy/deploy.sh`；目标机需预先具备 ACR 拉取权限 |
| 验收 | 在可信调用方验证 JWT、SSE、取消、会话续接；按需验证真实模型、数据库及附件/DOCX |

流水线阶段名称以云效当前界面为准。云效组织、仓库连接、ACR 服务连接、主机组须在实际账号中配置。
构建机和主机应使用相同 CPU 架构；都需要 Docker，主机需要 Compose >=2.30（raw env_file）和 `flock`。
镜像内包含 Python、SDK/CLI 和 Node/DBHub，主机不再单独安装 Python/Node。
Docker Hub 不通时可设置 `NODE_IMAGE`、`PYTHON_IMAGE` 为组织 ACR 中同步的对应 Debian Bookworm 官方镜像（建议固定 digest）；不要替换为来源不明的镜像。

## 配置与数据

- 运维将 `runtime.env.example` 的实际配置放到主机 `/etc/ccsdkscribe/runtime.env`；目录限制访问，文件权限 `0600`，由有 Docker 权限的部署账号读取。密钥也可由 Secret Manager 在部署阶段生成到该路径。
- 通用配置通过容器环境注入；不要上传本机 `.env`，不要用构建参数传密钥，不要运行会展开密钥的 `docker compose config`（脚本只用 `--quiet`）。`runtime.env` 是 raw 格式，值不加外层引号，`$` 原样传入。
- 问数另备 `/etc/ccsdkscribe/database-qa.env`，内容按 Workflow 的 `workflow.env.example`，只读挂载。文件需允许容器 UID 10001 读取，例如属主 10001、权限 `0400`；设置 `CCSDK_WITH_DATABASE=1` 启用。此文件由 python-dotenv 解析，不使用 Compose raw 语法。
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
- 2026-09-11 本地 Linux/amd64 镜像验证：87 项测试通过，UID 10001 下 SDK CLI、Node 和 DBHub demo 启动成功；容器健康检查与未授权 Run 返回 401 通过。未使用真实模型/数据库凭据，云效及 ECS 未部署验收。

## 离线镜像导入

本地导出的 `dist/ccsdkscribe-20260911-linux-amd64.tar` 可通过 `docker load -i ccsdkscribe-20260911-linux-amd64.tar` 导入；镜像名为 `ccsdkscribe:20260911`。
导入后准备上述主机配置，在 `deploy/` 执行 `CCSDK_IMAGE=ccsdkscribe:20260911 docker compose up -d --wait`；问数加 `-f compose.yaml -f compose.database.yaml`。
离线导入不执行 `deploy.sh` 的仓库拉取步骤；不要把镜像 tar 提交到 Git。后续发布使用提交 SHA 或 digest 标识镜像。

## 本次工程要求检查

| 要求编号 | 状态 | 依据 | 差距与后续处理 |
| --- | --- | --- | --- |
| REQ-001 | 部分满足 | 构建排除密钥；Workflow 凭据独立挂载；不改 MCP 选择性注入 | Java 真实透传、Token 撤销、跨租户执行隔离仍需端到端验收 |
| REQ-002 | 部分满足 | 原 HTTP 契约、Capability 映射和执行资产保留在 Runtime 镜像 | Java 业务授权、配置版本审计及生产接入仍需验收 |
