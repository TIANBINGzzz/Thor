# 架构决策记录（ADR）

ADR 记录重要架构取舍及其历史，不是实现任务清单。新文档使用 [模板](template.md)，实现任务另记 backlog；功能代码删除不等于删除决策记录。

## 编写约定

当前拆分边界见 [ADR-018：本地自测独立项目](018-extract-local-playground.md)，部分替代 ADR-011 的同仓本地应用边界；历史 ADR 中的 `web/` 和 `python/local/` 路径现位于外部 ScribePlayground。

- 适用：技术选型、安全边界、数据流向、存储及明确放弃的方案；普通修复、实现细节和临时想法不再新建 ADR。
- 存量修复类 ADR 保留编号和原始意图，不因新准则追溯删除。
- 必填：元数据表、背景、决策、实现证据与差距、后果、工程要求检查、状态变更记录。
- 正文优先 20-30 行，含必填记录最多 50 行；长协议放 specs 并链接，后果用好处/代价/风险三条简述。
- 元数据用表格，避免 Markdown 将连续字段折叠为一个段落；标题统一为 `ADR-NNN: 标题`。
- 每次改方案逐条核对 [工程要求](../specs/engineering-requirements.md)；填写编号、状态、依据、差距，不适用须说明原因。

## 两类状态

决策状态表示方案是否仍有效，实现状态表示该 ADR 范围内的代码落地程度；“已采纳”不表示“已实现”，“已实现”不表示生产端到端验收。

| 决策状态 | 含义 |
| --- | --- |
| 提议 | 尚未采纳，不能当作现行架构依据 |
| 已采纳 | 当前架构依据，实现可以尚未开始 |
| 已替代 | 已由其他 ADR 取代，必须填入后继链接及替代范围 |
| 已废弃 | 不再适用且无明确后继，记录原因和日期 |
| 已拒绝 | 讨论后明确不采用，保留理由 |

| 实现状态 | 含义 |
| --- | --- |
| 未开始 | 尚无该决策的实现；不能仅因缺少验收就判为未开始 |
| 进行中 | 已在开发，但主要路径尚未形成 |
| 部分实现 | 已有部分路径，仍有实现或验收缺口，逐项说明 |
| 已实现 | 声明范围已有足够落地证据，必须注明验证层级及未覆盖范围 |
| 不适用 | 原则无需功能交付，或历史/拒绝方案不再要求当前实现，须说明原因 |
| 待核验 | 证据不足，暂不能判断；记录待查范围，不猜测进度 |

提议通常为“未开始”，不能仅因尚未批准就写“不适用”。源码能确认落地范围，但未执行的测试、模拟服务测试和真实外部链路验收必须分开记录；旧报告只可作有日期的历史证据。

## 生命周期与替代关系

1. 新决策从“提议 + 未开始”起步；已有明确采纳依据可据实填写，不能凭代码存在自动宣布批准。
2. 决策通常从提议走向采纳或拒绝，采纳后可被替代或废弃；实现状态独立更新，发现回归/缺口时也可以回退。
3. 新 ADR 的“替代的旧 ADR”指向旧文档；旧 ADR 的“被哪份 ADR 替代”指向新文档，必须双向一致。部分替代须写范围，剩余有效决策不整体标成已替代。
4. 状态改变须同步正文元数据、状态变更记录和本页索引。决策日期保留原值，最近核对填实际核对日期。
5. 补录存量 ADR 只记录本次核对，不虚构历史采纳/完成/替代时间。重大决策改变新建 ADR，不能将新方案伪装成旧决策。
6. 已索引或被引用的 ADR 默认不删除；废弃、拒绝、替代均保留正文。未索引且未引用的误建/重复草稿可删除。
7. 确需物理删除时，索引必须保留无链接墓碑：编号、标题、已删除、原因、日期、替代编号；检查引用，Git 历史是恢复来源。
8. “已删除”只是文档处置结果，不是决策状态；旧实现状态保留在历史记录，不能用“不适用”抹去过去的交付事实。

## 当前索引

核对日期：2026-09-07。当前主目录保留 6 篇现行 ADR；历史 ADR 归档于 `doc/archive/ADR/`。005 在目录及本次可见 Git 历史查询中未找到，不补造条目、不认定为已删除。

| 编号 | 标题 | 决策状态 | 实现状态 | 范围与差距 |
| --- | --- | --- | --- | --- |
| [001](../archive/ADR/001-no-backward-compatibility.md) | 不保留向后兼容 | 已采纳 | 不适用 | 开发期原则；兼容边界仍须显式说明 |
| [002](../archive/ADR/002-mcp-for-database.md) | 使用 MCP 动态挂载数据库 | 已采纳 | 已实现 | 本地 DB profile；未重跑真实问数 |
| [003](../archive/ADR/003-container-isolation-for-security.md) | 使用容器隔离工作目录 | 提议 | 未开始 | 容器部署与隔离验证未开始 |
| [004](../archive/ADR/004-reference-syntax-for-large-datasets.md) | 引用语法处理大候选集 | 已采纳 | 已实现 | 本地分页与复核；无生产 ACL 验收 |
| [006](../archive/ADR/006-reference-and-skill-improvements.md) | 引用系统完善 | 已采纳 | 已实现 | 后端测试通过；前端仅源码核对 |
| [007](../archive/ADR/007-file-upload-pending-mode.md) | 文件上传改为待上传模式 | 已采纳 | 已实现 | 待上传交互已有代码；未重跑浏览器 |
| [008](../archive/ADR/008-session-file-context-optimization.md) | 会话文件上下文优化 | 已采纳 | 已实现 | 本地文件上下文；未重跑真实模型 |
| [009](../archive/ADR/009-fix-file-registration-and-chip-display.md) | 修复文件上传注册和 Chip 显示 | 已采纳 | 已实现 | 上传注册测试通过；未重跑视觉验收 |
| [010](../archive/ADR/010-file-upload-and-conversation-consistency.md) | 文件上传与文件对话一致性 | 已采纳 | 部分实现 | 真实上传/长对话/DOCX 交付待验收 |
| [011](011-python-application-backend.md) | 应用后端统一使用 Python | 已采纳 | 已实现 | Python 后端迁移；生产接入另行跟踪 |
| [012](../archive/ADR/012-provider-neutral-agent-runtime.md) | Java 控制面与 Provider-neutral Agent Runtime | 已替代 | 不适用 | 被 ADR-013、014 替代，保留历史 |
| [013](013-java-python-runtime-contract.md) | Java 控制面与 Python CCSDK Runtime 契约 | 已采纳 | 部分实现 | Python 协议已接入；Java 与权限闭环待验收 |
| [014](014-ccsdk-runtime-mvp.md) | CCSDK Runtime 方案二 MVP | 已采纳 | 部分实现 | 单实例路径已接入；加密/多实例/生产验收仍缺 |
| [015](015-query-client-runtime-lifecycle.md) | Query 与 ClaudeSDKClient 生命周期 | 已采纳 | 部分实现 | Actor/Client 测试通过；生产恢复仍缺 |
| [018](018-extract-local-playground.md) | 本地自测拆为独立项目 | 已采纳 | 已实现 | Runtime 75 项、Playground 18 项测试及真实 SDK 跨项目联调通过；未验收生产 Java |
| [016](016-file-broker-for-runtime-inputs.md) | Runtime 输入文件通过 File Broker 获取 | 已采纳 | 部分实现 | Python Broker 适配器已有；Java 真实附件链路未验证 |
| [017](017-capability-catalog-and-template-confirmation.md) | 能力目录与模板确认状态 | 提议 | 部分实现 | 静态原型已验证；Java 配置/草稿与 Python 目录/v2 待实现 |
| [019](019-shared-query-spec-assets.md) | 问数与撰写共享 QuerySpec 查询资产 | 已采纳 | 部分实现 | 查询资产、18问及模板绑定已整理验证；运行时执行和报告库待接入 |
| [020](020-separate-data-sources-and-connections.md) | 业务数据源与物理连接分离 | 提议 | 未开始 | 分离方向已确认；具体多库绑定、连接工具与权限执行设计待接入 |

## 本次核验

- 2026-09-07：`python -m unittest discover -s python/tests -t python -p 'test_*.py'`，134 项通过；涉及 SDK、Broker 和内部 Runtime 的测试包含替身，不代表外部服务联调。
- 前端仅核对当前生效组件及调用路径；本次未运行前端测试、浏览器交互、真实 Provider/数据库或外部 Java 验收。
- 本次检查通过：15 篇必填结构、状态枚举、元数据/历史/索引一致性、替代双向链接及 77 个相对链接；正文 42-49 行，模板 46 行，均未超过 50 行。ADR 范围的 `git diff --check` 通过。
- REQ-001、REQ-002 已逐篇登记适用性和差距；本次只维护 ADR，不将现有 Token、Capability 或兼容约定的差距认定为已解决。
