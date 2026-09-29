# 运行与部署

所有命令从仓库根目录执行，另有说明除外。环境字段见 `.env.example`、[runtime.env.example](runtime.env.example)；数据库及文件服务见 [配置字段](../config/README.md)。

## 本地开发

安装 `requirements.txt`，从 `.env.example` 准备 `.env` 并配置模型和 Runtime JWT；本机代理等差异写 `.env.local`，加载顺序为 `.env`、`.env.local`、所选 Workflow 的 `workflow.env`。前两者均不提交、不进入镜像，部署不携带本机覆盖。`python python/server.py` 或 `npm start` 启动，默认 `127.0.0.1:4310`，端口由 SCRIBE_PORT 指定。

回归使用 `npm test`；部署配置回归用 `python -m unittest discover -s deploy -p "test_*.py"`。真实 API/模型验证用 `deploy/smoke.py`，参数见 `--help`；单元测试不能代替真实模型、Java 授权和成稿验收。

文档编辑依赖 OfficeCLI，版本、来源和校验值见 [构建依赖](vendor/officecli/README.md)。Linux 镜像内置 LibreOffice/PDFium；Windows 开发先构建 `docker build --target document-renderer -t ccsdkscribe-renderer:local .`，可用 CCSDK_RENDER_IMAGE 指定镜像。渲染复测入口为 `scripts/benchmark-document.py`。

## 构建与交付

| 路线 | 入口与前提 |
| --- | --- |
| 云效镜像包 | `flow.yml` -> `build.sh` -> `image.tar` 制品 -> `deploy.sh`/Compose；部署机无需访问镜像仓库，但需可下载制品 |
| 仅构建 | 将 `flow-build.stages.yml` 用作 Flow 的 stages，保留组织自己的 sources/defaultWorkspace；无需运行密钥或部署主机组 |
| 外部 ACR 发布 | 主机维护的 `update_python.sh` 拉镜像并用 env-file 创建容器，不经过本仓库 deploy.sh/Compose/配置生成器 |

两条发布路线共用镜像 `entrypoint.py`。构建使用可信 Linux amd64 Docker/BuildKit 环境，基础镜像、PyPI、Debian 源与制品服务须可达；NODE_IMAGE/PYTHON_IMAGE/PIP_INDEX_URL/DEBIAN_MIRROR 可覆盖镜像源。OfficeCLI 随源码校验交付，不在构建时从 GitHub 下载。

Flow 模板的 Codeup 服务连接、代码源、分支及主机组 ID 由实际组织配置替换，不以 UI 显示名代替 ID；CCSDK_DEPLOY_ROOT 必填、无默认值，指向专用持久目录，预先创建其 packages/ 子目录。镜像标签取实际 Git 提交及 BUILD_NUMBER，发布前确保源码已进入所选分支。

## 配置与边界

- 默认数据库配置随私有源码复制到容器 `/app/config/databases.json`；CCSDK_WITH_DATABASE=0 不挂载覆盖。修改内置配置须重建镜像，例外范围见 [ADR-028](../doc/ADR/028-bundled-database-config.md)，构建不验证内网数据库连通性。
- 外置覆盖使用 CCSDK_WITH_DATABASE=1，配置目录只读挂到 `/app/deployment-config`，不遮住镜像内 Nacos 配置。云效生成模式用 CCSDK_GENERATE_ENV=1、私密 CCSDK_DEPLOY_ENV_B64，数据库另用 CCSDK_DATABASES_JSON，可选证书用 CCSDK_DATABASE_CERTIFICATES_JSON；示例分别见 secrets.example.json/data-access.example.json。
- 主机自行维护配置时用 CCSDK_GENERATE_ENV=0，不与云效重复维护；CCSDK_CONFIG_DIRECTORY 指定目录，deploy.sh 按调用工作目录解析相对路径并转为绝对路径，直接使用 Compose 时相对路径按 Compose 项目目录解析。数据库/CA 的文件内字段与路径基准以配置说明为准。
- 使用 `python deploy/encode-secret.py <私有JSON> <输出文件>` 生成传输内容；Base64 不是加密，输入输出均按密钥保管，不提交 Git、不用在线编码、不打印环境。模型/JWT 由运行环境注入，禁止挂载根 `.env` 覆盖容器配置。
- Compose raw env_file 写实际值，不加 dotenv 外层引号；配置变更须重新创建容器，docker restart 不刷新环境。容器配置只读且服务 UID 为 10001，文件权限须匹配，不能用 chmod 777。
- Compose 路线需要 Docker、Compose >=2.30、flock、tar、sha256sum 及相应主机权限。镜像固定容器内端口 4310，外部访问通过映射配置；127.0.0.1 在容器中指容器自身，代理、数据库和文件服务地址须实际可达。
- Nacos 启动与认证字段见 [配置说明](../config/README.md#配置加载与注入)。各环境可只读挂载自己的 `application.yml`；host 网络可用 `127.0.0.1:8848`，bridge 网络连接宿主机时使用 `host.docker.internal:8848` 和 `host-gateway` 映射。确认 env-file 中没有旧的 `CCSDK_NACOS_*` 覆盖部署 YAML。
- CCSDK_BIND_IP 默认主机回环；跨机访问绑定内网并限制来源。SSE 反向代理关闭缓冲、配置长连接超时；JWT 时钟、issuer/audience 和共享密钥与 Java 一致。
- 单副本、单 HTTP worker；命名卷保存 `.scribe-runs/` 的记录、SDK 历史和文件。已有部署用 CCSDK_DATA_VOLUME 保持原卷，禁止 `docker compose down -v`，改卷名不会迁移数据。

## 验证与回滚

`build.sh` 运行镜像测试并导出校验和；部署校验 SHA-256 后 docker load，以 Compose `--pull never` 启动。CCSDK_SMOKE_TEST=1 增加健康、未认证拒绝、签名 Run、真实模型和 SSE 检查；关闭时不能宣称真实链路通过。

发布前由调用方停止新 Run 并等待活动任务结束；没有自动排空或无损滚动更新。保留历史制品和数据备份，以上一制品重新部署回滚，并核对配置/数据兼容性；模型失败不自动回滚。历史测试及仍未验收的范围见 [验收记录](../doc/verification/acceptance.md)。

## HTML 文档发布

接口参考发布为 [Python API 文档](https://cp.stringedu.com/ccsdkscribe/python-api.html)。设置 CCSDK_DOCS_RELEASE_SCRIPT/CCSDK_DOCS_INCOMING_DIRECTORY，或传 -RemoteReleaseScript/-RemoteIncomingDirectory；远端路径须符合脚本的 POSIX 路径白名单。

运行 `powershell -ExecutionPolicy Bypass -File ./scripts/publish-docs.ps1`：只提交 HTML 改动、上传确定 Git 版本、原子切换并核对公网 SHA-256，不执行 git push，也不提交其他暂存文件。回滚传 `-RollbackRelease <Previous>`，通常无需重载 Nginx。

远端脚本由 SSHCloudServer 项目的 `deploy/ccsdkscribe-docs/` 维护，本地依赖 Windows Git、OpenSSH 和 curl。文档整理或本地提交本身不代表已发布公网。
