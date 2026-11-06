# 运行与部署

所有命令从仓库根目录执行，另有说明除外。完整启动与 Nacos 配置的本机、example、production 三版本见[配置字段](../config/README.md)。

跨会话查找 newtest（57，单租户测试）、cloud（59，单租户正式）、appai（多租户测试）的连接、凭据、部署位置及云效信息，先读本机私有 [环境交接](environments.local.md)；该文件不提交、不进入镜像，新克隆需单独提供。

## 本地开发

安装 requirements.txt，从 config/application.example.yml 准备完整 config/application.yml；按带注释的 Nacos 客户模板填入配置中心。本机文件已保留真实值，不提交、不进镜像。只加载 YAML，不加载 env 或 .local 覆盖。python python/server.py 或 npm start 启动，监听地址/端口取 application.server。

回归使用 `npm test`；部署配置回归用 `python -m unittest discover -s deploy -p "test_*.py"`。真实 API/模型验证用 `deploy/smoke.py`，参数见 `--help`；单元测试不能代替真实模型、Java 授权和成稿验收。

文档编辑依赖 OfficeCLI，版本、来源和校验值见 [构建依赖](vendor/officecli/README.md)。Linux 镜像内置 LibreOffice/PDFium；Windows 开发先构建 `docker build --target document-renderer -t ccsdkscribe-renderer:local .`，可在 application.tools.render-image 指定镜像。渲染复测入口为 `scripts/benchmark-document.py`。

## 构建与交付

| 路线 | 入口与前提 |
| --- | --- |
| 云效镜像包 | `flow.yml` -> `build.sh` -> `image.tar` 制品 -> `deploy.sh`/Compose；部署机无需访问镜像仓库，但需可下载制品 |
| 仅构建 | 将 `flow-build.stages.yml` 用作 Flow 的 stages，保留组织自己的 sources/defaultWorkspace；无需运行密钥或部署主机组 |
| 外部 ACR 发布 | 主机维护的 update_python.sh；原 env-file 启动须改为只读挂载完整 application.yml，再发布此版本 |

两条发布路线共用镜像 `entrypoint.py`。构建使用可信 Linux amd64 Docker/BuildKit 环境，基础镜像、PyPI、Debian 源与制品服务须可达；NODE_IMAGE/PYTHON_IMAGE/PIP_INDEX_URL/DEBIAN_MIRROR 可覆盖镜像源。OfficeCLI 随源码校验交付，不在构建时从 GitHub 下载。

Flow 模板的 Codeup 服务连接、代码源、分支及主机组 ID 由实际组织配置替换，不以 UI 显示名代替 ID；CCSDK_DEPLOY_ROOT 必填、无默认值，指向专用持久目录，预先创建其 packages/ 子目录。镜像标签取实际 Git 提交及 BUILD_NUMBER，发布前确保源码已进入所选分支。

## 配置与边界

- 启动文件从 config/application.production.yml 填写，客户配置从 config/nacos-ai-center-agent-service.production.yml 填写并导入 Nacos。模板凭据不可直接启动，不将真实配置打入镜像。
- 主机预先准备 CCSDK_CONFIG_DIRECTORY/application.production.yml；也可用 CCSDK_APPLICATION_FILE 选择已填好的完整 YAML。deploy.sh 的相对路径基准为脚本所在 deploy 目录；直接使用 Compose 时为 Compose 项目目录。部署脚本只选挂载源、镜像及资源参数，不覆盖应用配置字段。
- YAML 只读挂载到 /app/config/application.yml，配置文件及父目录须允许 UID 10001 读取/进入，不用 chmod 777。缺失挂载源直接失败，不自动生成空文件或目录。数据库 CA 按 Nacos connection.tls.ca_file 指定路径另行只读挂载，相对路径基准为 /app/config。
- Flow 只构建和部署，不生成 env 或传输密钥包；主机须在部署前准备完整生产 YAML。镜像内生产模板只用于声明结构，不能代替实际配置。
- Compose 路线需要 Docker、Compose >=2.30、flock、tar、sha256sum 及相应主机权限。标准容器端口为 4310，application.server 使用 0.0.0.0:4310，外部访问通过端口映射；代理和业务地址须从容器实际可达。
- Nacos host 网络可用 127.0.0.1:8848；bridge 连接宿主机时用 host.docker.internal:8848 和 host-gateway 映射。连接引导与读取超时只在启动 YAML，客户和完整 runtime 参数只在 Nacos，无本地回退。
- CCSDK_BIND_IP 默认主机回环；跨机访问绑定内网并限制来源。SSE 反向代理关闭缓冲并配置长连接超时；JWT 时钟、issuer/audience 和密钥与 Java 一致。
- 单副本、单 HTTP worker；命名卷保存 .scribe-runs/ 的记录、SDK 历史、文件和管理端新建能力。已有部署用 CCSDK_DATA_VOLUME 保持原卷，禁止 docker compose down -v，改卷名不会迁移数据。

配置变更排空任务后重启，无需重建镜像。构建只校验源码资产，不连接客户 Nacos 或数据库；部署 --check 连接 Nacos，probe 另查数据库，均不代表真实业务验收。

## 独立观测接入

Nacos runtime.observability.enabled 控制采集；开启后采集脱敏事件并写入有界待采库。采集平台与 Runtime 使用相同 observationJwtSecret，该密钥与执行及管理密钥分离。Hawkeye 接入源填写 Runtime 根地址，实例标识及游标由平台发现和维护；替换待采库后重新登记。

带专用 observation.read JWT 核对 /internal/observability/v1/info、records、snapshot、metrics；关闭返回404，缺密钥返回503，无效授权返回401。紧急停采在 application.diagnostics.disable-observability 设置 true 并重启；正常采集以 Nacos 为准。

## 验证与回滚

`build.sh` 运行镜像测试并导出校验和；部署校验 SHA-256 后 docker load，以 Compose `--pull never` 启动。CCSDK_SMOKE_TEST=1 增加健康、未认证拒绝、签名 Run、真实模型和 SSE 检查；关闭时不能宣称真实链路通过。

发布前由调用方停止新 Run 并等待活动任务结束；没有自动排空或无损滚动更新。保留历史制品和数据备份，以上一制品重新部署回滚，并核对配置/数据兼容性；模型失败不自动回滚。历史测试及仍未验收的范围见 [验收记录](../doc/verification/acceptance.md)。

## HTML 文档发布

接口参考发布为 [Python API 文档](https://cp.stringedu.com/ccsdkscribe/python-api.html)。设置 CCSDK_DOCS_RELEASE_SCRIPT/CCSDK_DOCS_INCOMING_DIRECTORY，或传 -RemoteReleaseScript/-RemoteIncomingDirectory；远端路径须符合脚本的 POSIX 路径白名单。

运行 `powershell -ExecutionPolicy Bypass -File ./scripts/publish-docs.ps1`：只提交 HTML 改动、上传确定 Git 版本、原子切换并核对公网 SHA-256，不执行 git push，也不提交其他暂存文件。回滚传 `-RollbackRelease <Previous>`，通常无需重载 Nginx。

远端脚本由 SSHCloudServer 项目的 `deploy/ccsdkscribe-docs/` 维护，本地依赖 Windows Git、OpenSSH 和 curl。文档整理或本地提交本身不代表已发布公网。
