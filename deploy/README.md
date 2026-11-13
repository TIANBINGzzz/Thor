# 运行与部署

所有命令从仓库根目录执行，另有说明除外。完整启动与 Nacos 配置的本机、example、production 三版本见[配置字段](../config/README.md)。

跨会话查找 newtest（57，单租户测试）、cloud（59，单租户正式）、appai（多租户测试）、ai（多租户正式）的连接、凭据、部署位置及云效信息，先读本机私有 [环境交接](environments.local.md)；该文件不提交、不进入镜像，新克隆需单独提供。

## 本地开发

安装 requirements.txt，从 config/application.example.yml 准备完整 config/application.yml；按带注释的 Nacos 客户模板填入配置中心。本机文件已保留真实值，不提交、不进镜像。只加载 YAML，不加载 env 或 .local 覆盖。python python/server.py 或 npm start 启动，监听地址/端口取 application.server。

回归使用 `npm test`；部署配置回归用 `python -m unittest discover -s deploy -p "test_*.py"`。真实 API/模型验证用 `deploy/smoke.py`，必须传本次获准的 `--tenant` 和 `--domain-name`；单元测试不能代替真实模型、Java 授权和成稿验收。

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
- 单副本、单 HTTP worker；命名卷保存 .scribe-runs/ 的记录、SDK 历史、文件。已有部署用 CCSDK_DATA_VOLUME 保持原卷，禁止 docker compose down -v，改卷名不会迁移数据。

配置变更排空任务后重启，无需重建镜像。构建只校验源码资产，不连接客户 Nacos 或数据库；部署 --check 连接 Nacos，probe 另查数据库，均不代表真实业务验收。

## 独立观测接入

Nacos runtime.observability.enabled 控制采集；开启后采集脱敏事件并写入有界待采库。采集平台与 Runtime 使用相同 observationJwtSecret，该密钥与执行及管理密钥分离。Hawkeye 接入源填写 Runtime 根地址，实例标识及游标由平台发现和维护；替换待采库后重新登记。

带专用 observation.read JWT 核对 /internal/observability/v1/info、records、snapshot、metrics；关闭返回404，缺密钥返回503，无效授权返回401。紧急停采在 application.diagnostics.disable-observability 设置 true 并重启；正常采集以 Nacos 为准。

## 验证与回滚

`build.sh` 运行镜像测试并导出校验和；部署校验 SHA-256 后 docker load，以 Compose `--pull never` 启动。CCSDK_SMOKE_TEST=1 且显式设置 CCSDK_SMOKE_TENANT 增加健康、未认证拒绝、签名 Run、真实模型和 SSE 检查；关闭时不能宣称真实链路通过。

发布前由调用方停止新 Run 并等待活动任务结束；没有自动排空或无损滚动更新。保留历史制品和数据备份，以上一制品重新部署回滚，并核对配置/数据兼容性；模型失败不自动回滚。历史测试及仍未验收的范围见 [验收记录](../doc/verification/acceptance.md)。

## 回归题目与验收

自动测试输入在 `python/tests/test_*.py` 及其夹具；基础模型冒烟题在 `deploy/smoke.py`。真实能力回归统一使用下列来源，不自动并入 `npm test` 或云效构建；每次完整能力回归包含两套问数题库、简单撰写及预热池6并发观测，专项抽测须列出选题及未测范围。创建 Run 时须同时传本次学校的 `domainName`，冒烟与压测脚本以 `--domain-name` 接收。

| 能力 | 题目来源 | 预期结果 |
| --- | --- | --- |
| 校园大脑问数 | 同级 Eval 项目的 [职业院校对比与常模分析测试问题集.json](../../Eval/职业院校对比与常模分析测试问题集.json) | 保留题目顺序及多轮会话关系；答案的指标、年份、学校范围、排名/常模类型与授权上游证据一致，缺项明确披露 |
| 双高问数 | 同级 Eval 项目的 [双高问题测试集.json](../../Eval/双高问题测试集.json) | 与独立只读查询基准核对数值、年度、单位及项目/租户范围；缺失值不当作零，当前值不冒充历史值 |
| 简单撰写 | 下方 `WRITING-SMOKE-01` | 实际生成、发布并授权下载 DOCX/PDF；事实、结构和逐页格式均通过 |

题库按仓库根目录的 `../Eval/` 查找，JSON 是唯一维护和执行来源，原 Word 仅作转换来源保留；结构及待补条件见 [Eval 题库约定](../../Eval/README.md)。按 `cases` 选题，同一用例的 `turns` 顺序共用业务会话，不同用例新开会话；`needs_context` 不直接执行，`needs_parameters` 须先绑定必需参数，未执行/被阻塞单列，不计通过。题目不复制到执行资产；缺失时报告未执行，不用仓内 `midterm-qa-cases.json` 替代（该文件用于中期报告查询覆盖检查）。执行前记录源码版本、环境、模型、题库文件摘要、用例/轮次编号、执行日期及时区，原始问题、实际发送文本、答案、Run/SSE、基准与文件只留忽略的 `scratch/`。真实身份和凭据沿既有授权链路提供，不写入题目。

`WRITING-SMOKE-01`：选择 `document-writing`，新建会话，不选预制模板、不附文件；发送以下完整题目：

> 请只根据以下虚构测试资料，生成《教师数字化教学培训简报》，交付可下载的 DOCX 和 PDF。资料：2026年11月6日，教学发展中心在实训楼201室举办培训，24名教师参加；两个环节依次为“教学平台操作演示”（40分钟）、“课件制作练习”（50分钟）。不得增加讲师、满意度、考核结果等未提供事实，不联网、不查询数据库。正文约250—400字，包含“活动概况”“培训安排”“资料缺项”三个一级标题；“培训安排”下放一个3列、3行的表格，表头为“环节、内容、时长”，两条数据为“1、教学平台操作演示、40分钟”和“2、课件制作练习、50分钟”。资料缺项明确写“讲师、满意度及考核结果未提供”。使用A4纵向、四边页边距2.5厘米、标题居中黑体16磅、一级标题黑体14磅、正文宋体12磅；全文1—2页，无需目录，表格有可见边框。

验收分别记录“链路、内容、格式”，全部通过才判本用例通过：

- 链路：真实模型执行到 `run.completed`，DOCX/PDF 均为可用成果并能通过授权文件接口下载；下载内容与发布文件摘要一致。只有文字承诺、附件链接或上传 ready 不算通过。直连 Runtime 的结果不得写成 Java 全链路通过。
- 内容：标题、日期、地点、24人、两环节及40/50分钟准确；三个章节和缺项说明齐全，未补写未知事实；正文长度符合题目要求，表格内容逐格核对。
- 格式：DOCX 可被文档解析器打开，含真实段落/表格及标题样式；核对纸张、页边距、字体字号、对齐和表格行列/边框。PDF 可解析且1—2页，全文与DOCX一致；逐页渲染检查中文、表格、换行，无乱码、裁切、重叠或多余空白页。复用 `scripts/benchmark-document.py`、`scripts/audit-report.py` 辅助核验，脚本成功不能替代视觉检查。
- 结果：保存输入、Run标识、执行终态、耗时、脱敏错误、文件摘要、结构检查和页面核验结论。失败分为链路、内容或格式失败；未执行/被阻塞单列，不计通过。简单撰写通过不代表预制/上传模板、长报告或复杂目录验收通过。

### 预热池与6并发：POOL-SMOKE-01

沿用既有业务授权和独立 `observation.read` 观测授权，通过 `/internal/observability/v1/snapshot` 每秒采样，并按游标收集 `records` 的 `pool`、`prewarm` span、`client_acquired` 及 Run 耗时；记录丢失、游标缺口或权限不足时不能判通过。原始证据放本轮 `scratch/`，记录观察起点和终点。

执行前记录 `max-idle`、`max-starting`、`max-live`、内存阈值及观察窗口（默认每阶段120秒，可事先按环境调整，属于测试截止时间而非产品SLA）。六次预热命中以目标配置匹配的ready至少6个且有补池容量为前提；条件不足单列，不擅自调整线上配置。先检查宿主机和容器有效剩余内存、磁盘、OOM记录及 `memory_paused`；内存保护触发时标为环境阻塞，不降低保护阈值强跑。暂停后的后台预热需有效剩余内存达到阈值2倍且经过30秒冷却。

| 阶段 | 输入与执行 | 期待输出与判断 |
| --- | --- | --- |
| 初始预热 | 在内存恢复或已授权启动后观察；不为测试擅自重启服务 | 容量充足时 `ready` 达到配置目标（通常6）；记录首个可用、全部就绪和单Worker预热耗时；已有满池但无启动证据时，启动速度记未测 |
| 首轮6并发 | 同配置的6个独立新会话，同时发送基础算术题 | 六轮均完成且答案为391；每轮关联不同Client/Worker归属，`client_acquired.source=prewarmed`；记录领取耗时、首字和总耗时，不能只凭总hits变化判本轮命中 |
| 消耗后补池 | 从领取发生前持续观测至库存恢复 | 在容量和内存允许时自动补回目标，记录首次库存下降至恢复耗时、最低ready和补充数量；`starting + businessStarting` 不超 `max-starting`，live不超非零 `max-live`，无持续失败重建 |
| 复用与再次命中 | 先让原6会话同时续聊一轮，再等满池后新建另一组6会话并发 | 续聊6/6为 `session_reuse`，不当作预热命中；新会话6/6命中预热，再次自动补池；三轮共18次请求，前后轮独立统计 |

同步记录 ready/starting/reserved/live/retiring、hits/misses/failures增量、memory_paused、宿主机可用内存、容器内存/CPU/PID及OOM增量；按阶段输出预热、补池、领取、首字和总耗时的样本数、中位数、P95与最大值。六样本的P95通常等于最大值，不据此推断生产容量；无既定速度基线时只报告实测，不宣称提速。

达到live上限或仍受内存保护时，补不满记容量/环境受限；资源充足却超出观察窗口未补齐记失败。请求须无错误、无凭据/会话串用、无OOM或进程持续增长；与非测试会话交叠导致无法归因的指标记未核实。`deploy/loadtest.py --concurrency 6` 可复用基础负载和资源采样，但其默认多轮只续用同一组会话，不能单独证明新会话补池与再次命中；须补充上述阶段及观测证据。

## HTML 文档发布

接口参考发布为 [Python API 文档](https://cp.stringedu.com/ccsdkscribe/python-api.html)。设置 CCSDK_DOCS_RELEASE_SCRIPT/CCSDK_DOCS_INCOMING_DIRECTORY，或传 -RemoteReleaseScript/-RemoteIncomingDirectory；远端路径须符合脚本的 POSIX 路径白名单。

运行 `powershell -ExecutionPolicy Bypass -File ./scripts/publish-docs.ps1`：只提交 HTML 改动、上传确定 Git 版本、原子切换并核对公网 SHA-256，不执行 git push，也不提交其他暂存文件。回滚传 `-RollbackRelease <Previous>`，通常无需重载 Nginx。

远端脚本由 SSHCloudServer 项目的 `deploy/ccsdkscribe-docs/` 维护，本地依赖 Windows Git、OpenSSH 和 curl。文档整理或本地提交本身不代表已发布公网。
