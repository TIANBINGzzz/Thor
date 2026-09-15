# 云效内网 Docker 部署

`flow.yml` 是 CCSDKScribe 的 Flow YAML 模板。它采用“构建机生成镜像包，97 导入镜像并启动”的路线，目标机不需要 Python、Node.js 或访问镜像仓库。

## 构建机怎么选

默认使用 `public/cn-beijing` + 官方 `alinux3` 构建容器，并开启 `enableDockerDaemon: true`。`LARGE_4C8G`（4 vCPU、8 GiB、约 50 GB 临时盘）是当前起点；Docker 构建内存不足再升到 `XLARGE_8C16G`。构建机每次是临时环境，代码、pip/npm、基础镜像和 Flow 制品服务必须能通过公网访问。北京/杭州集群适合国内资源，香港集群适合海外代码源。

如果组织没有公共构建集群，使用账号提供的 VPC 构建集群，或接入能访问公网的 Linux amd64 私有构建机。私有 VM 需把 `runsOn` 改成 `group: private/<构建集群ID>`、`labels: linux,amd64`、`vm: true`，移除 `container`、`instanceType` 和 `enableDockerDaemon`，并预装 Docker/BuildKit。97 只做部署机即可。

构建失败时先区分：申请构建环境失败是构建容器/网络问题，`docker build` 拉基础镜像或 pip/npm 超时是出网问题，部署阶段下载制品失败是 97 到云效制品服务的问题。完全离线客户使用本流水线生成的 `image.tar` 制品，现场 `docker load`。

构建访问基础镜像仓库、PyPI、Debian源及云效代码/制品服务。Docker Hub不通时配置NODE_IMAGE/PYTHON_IMAGE为组织同步的官方Bookworm镜像。镜像已包含SDK、Node和Python数据库依赖，移除DBHub及npm依赖安装；本机构建成功不代表云效目标网络已验收。

## 运行前置条件

- 97 已安装 Docker、Docker Compose `>=2.30`、`flock`、`tar`、`sha256sum`，并由云效主机组 Runner 以 root 执行。
- 97 为 Linux amd64。在 Flow UI 创建普通字符变量 `CCSDK_DEPLOY_ROOT`，由管理员填写专用于本服务的持久化绝对目录；无默认值。管理员提前创建其 `packages/` 子目录，部署脚本生成 `releases/` 和 `config/`。该目录不要放进其他服务发布目录。
- Java 或网关访问 Runtime 时，配置 `CCSDK_BIND_IP` 为 97 的内网地址并限制防火墙来源；同机反代可保持默认 `127.0.0.1`。
- Compose 命名卷 `ccsdkscribe-runtime-data` 保存运行记录、工作文件和 SDK 会话，升级时保留，禁止 `docker compose down -v`。

## Flow 变量和私密变量

在 Flow 的“变量和缓存”中创建 `CCSDK_DEPLOY_ENV_B64` 字符变量，打开**私密模式**，值来自本地命令：

```text
python deploy/encode-secret.py scratch/ccsdkscribe.secret.json scratch/ccsdkscribe.secret.b64
```

复制secrets.example.json为忽略的*.secret.json，填写后编码。必需模型配置和32字节以上JWT密钥；数据库另提供CCSDK_DATABASES_JSON（参照data-access.example.json，sources按来源键集中所有连接、用户名、密码及策略）。需要TLS证书时提供CCSDK_DATABASE_CERTIFICATES_JSON，格式为`{"schoolDoubleHigh.pem":"证书内容"}`，连接的tls.ca_file写`certificates/schoolDoubleHigh.pem`。不再提供单独数据库账号/密码变量。

CCSDK_WITH_DATABASE=1启用数据库挂载；CCSDK_GENERATE_ENV=1从云效变量生成runtime.env、databases.json及certificates/。配置目录只读挂载到容器/app/config，CCSDK_DATABASES_FILE固定为/app/config/databases.json；新增连接无需增加挂载。配置目录权限750、root:10001，数据库文件400、10001:10001，runtime.env保持root专用600。

学校现场可维护相同目录，CCSDK_GENERATE_ENV=0保留文件，升级只换镜像；Flow已开放此开关。不要同时在云效与主机维护同一环境。非Docker开发默认读取项目根config/databases.json，或由CCSDK_DATABASES_FILE指定；相对路径以项目根为准。学校切换地址、凭据、TLS及授权范围后排空任务并重新部署，无需重建镜像。

在“编辑流水线 → 变量和缓存 → 字符变量 → 新建变量”填写 `CCSDK_DEPLOY_ENV_B64`，打开私密模式，粘贴编码文件内容（不加引号）并保存。JSON 不要使用在线编码网站；用 JSON 字符串规则转义反斜线/双引号，值不能含换行。Base64 是传输编码，不是加密；编码文件和原 JSON 都按密钥保管，Windows 还需限制本地文件 ACL。

Flow 的私密变量支持 UI 配置或私密变量组，不支持在 YAML `variables.value` 存明文后标私密。变量组是流水线作用域；限制流水线编辑/执行权限，构建脚本不读取或打包该变量不等于构建环境无法访问它。不要输出环境或打开 `set -x`。客户换 Key 后更新私密变量并重新部署；无 Flow 时更新主机 `runtime.env`，用已导入镜像执行 `CCSDK_GENERATE_ENV=0` 的部署脚本。不要修改镜像保存 Key，单独 `docker restart` 不会刷新 env。

## 使用模板

首次只验证构建：先在 Flow 选择本项目 Codeup 仓库及 `main` 分支，保留平台生成的 `sources` 和对应 `defaultWorkspace`，仅用 [flow-build.stages.yml](flow-build.stages.yml) 替换整个 `stages` 段。它复用完整模板的构建阶段，不需要 ACR、97 主机组或运行密钥；构建成功不代表服务功能验收通过。

Python 示例的 `gitSample` 指向示例仓库，`DockerBuildPushACR.with.serviceConnection` 是镜像仓库连接，不能当作 Codeup 授权。运行前确认 Codeup 当前分支已有 `Dockerfile`、`requirements.txt`、`.dockerignore`、`deploy/build.sh`、`python/` 和 `.claude/`；仅粘贴流水线不会上传本地源码。

镜像标签使用工作区实际检出的 Git 提交及 `BUILD_NUMBER`，不依赖 `CI_COMMIT_SHA`。构建默认使用 ECR Public 的 Node/Python 基础镜像、阿里云 Debian/PyPI 源；可用 `NODE_IMAGE`、`PYTHON_IMAGE`、`PIP_INDEX_URL` 和 `DEBIAN_MIRROR` 覆盖。缺少项目文件时先检查代码源和默认工作区；这些前置检查失败说明尚未执行 Docker 构建。

将 `flow.yml` 导入 Flow 的 YAML 流水线后，替换：

1. `REPLACE_CODEUP_SERVICE_CONNECTION_ID`：能读取目标 Codeup 仓库的服务连接；分支 `main` 按仓库实际默认分支修改。
2. `REPLACE_MACHINE_GROUP_ID`：包含 `192.168.10.97` 的主机组 ID。截图中的“开发环境-192.168.10.97（业务系统）”是显示名，不是 ID；在主机组详情或 YAML 编辑器中复制真实 ID。
3. `CCSDK_DEPLOY_ROOT`：97 上的持久目录。

普通部署设置在 YAML 的variables修改：CCSDK_BIND_IP默认回环；CCSDK_WITH_DATABASE默认0，启用问数改1并提供databases.json；CCSDK_GENERATE_ENV默认1，现场维护配置改0。JWT密钥、issuer/audience要与Java一致。容器内127.0.0.1指容器自身，数据库host/port/database全部由集中配置提供。完整迁移问题见[checks/README.md](checks/README.md)。

构建任务会运行 `deploy/build.sh`：执行 Dockerfile 的完整 Python 测试，生成 `dist/release/image.tar`、镜像 ID、校验和及部署文件，然后通过 `ArtifactUpload` 上传。部署任务下载完整制品，校验 SHA256，`docker load` 后使用镜像内的 `write-env.py` 生成 `runtime.env`，再以 `docker compose --pull never` 启动。`CCSDK_SMOKE_TEST=1` 会额外执行健康、未认证拒绝、签名 Run、真实模型响应和 SSE 顺序检查；首次接入可先设为 `0`，待模型网络和 JWT 配置确认后再设为 `1`。

该模板依据云效官方的 [YAML 结构](https://help.aliyun.com/zh/yunxiao/user-guide/yaml-preliminary-experience/)、[构建集群](https://help.aliyun.com/zh/yunxiao/user-guide/build-a-cluster)、[环境变量](https://help.aliyun.com/zh/yunxiao/user-guide/variables) 和 [主机部署](https://help.aliyun.com/zh/yunxiao/user-guide/host-deployment-1) 编排。平台尚未验证资源 ID、主机组连接和 97 的网络；这些是上线前仍需在 Flow 中确认的项目。

发布会重建单 worker/单实例容器，先由调用方停止新 Run、等待活动任务结束；当前没有自动排空和无损滚动更新。模型失败会让任务失败，但不会自动回滚。保留历史制品及数据备份，通过上一版本制品重新部署回滚，配置/数据兼容性另核对。云效公共制品有保留期限，长期客户交付需另行归档。

## 本次工程要求检查

| 要求编号 | 状态 | 依据 | 差距与后续处理 |
| --- | --- | --- | --- |
| REQ-001 | 部分满足 | 密钥只在运行时生成配置；构建制品排除 env；沿用 MCP 按需注入 | Java 真 Token 透传、撤销和跨租户隔离仍需端到端验收 |
| REQ-002 | 部分满足 | 执行资产随镜像内部交付；Capability 已映射内部 Workflow | 真实 Java 业务授权、配置审计及生产隔离仍需端到端验收 |
