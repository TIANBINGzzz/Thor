# 知识库接入契约

决策与 WeKnora 权限调研见 [ADR-040](../ADR/040-knowledge-base-integration.md)。本文是表结构、解析规则和适配器边界的唯一来源；**当前未实现**，落地时以 `python/runtime/config_store.py` 的实际定义为准并同步本文。

## 设计原则

- **表不认识供应商**：列名只表达通用概念（连接、凭据、外部 ID）。供应商专属参数进 `config` JSON，由适配器在保存时校验。
- **学校归属挂在连接上**：一个连接就是一个隔离边界（WeKnora 的一个空间加一把只读 Key）。库只能属于一个连接，结构上无法把 A 校的库挂到 B 校的凭据下。
- **能力绑定用途，不绑定库**：能力声明“需要政策类、校本制度类知识”，每 Run 按本校身份把用途解析成库。新开学校只加连接和库，不改能力。
- **Runtime 只读**：配置库里只有检索权限的凭据；写入凭据和开通账号归 Java 管理端。

## 表结构

列风格沿用现有配置表：`ref` 主键 `String(96)`，显示名 `String(160)`，秘密字段加密后存 `Text`，扩展参数存 `JSON` 对象。

### `ccsdk_knowledge_connection`：连接（隔离边界）

| 列 | 类型 | 说明与原因 |
| --- | --- | --- |
| `ref` | String(96) PK | 稳定引用 |
| `name` | String(160) | 显示名，如“某校知识库”“公共政策库” |
| `provider` | String(48) | 适配器标识，目前只有 `weknora`；决定由哪个适配器校验 `credentials` 和 `config` |
| `base_url` | String(1024) | 供应商服务地址 |
| `tenant_id` | String(96) | 可使用该连接的学校：业务 Token 中的具体 `tenantId`，或 `*` 表示全部学校共享（公共政策）。不支持 `self`：SaaS 多校共用 Runtime 时，`self` 会让每所学校都匹配该连接 |
| `credentials` | Text | 加密的 JSON 对象。WeKnora 为 `{"api_key": "..."}`；用 JSON 而不是固定 `api_key` 列，是因为其他供应商可能需要 app_id 加 secret |
| `config` | JSON | 非秘密的供应商参数。WeKnora 为 `{"workspace_id": 123}`，适配器将其作为 `X-Tenant-ID` 发出 |
| `timeout_seconds` | Integer | 单次请求超时 |
| `max_results` | Integer | 单次检索条数上限，模型传入的 `limit` 不能超过它 |
| `enabled` | Boolean | 停用后该连接下所有库不参与解析 |

### `ccsdk_knowledge_purpose`：用途词表

| 列 | 类型 | 说明与原因 |
| --- | --- | --- |
| `ref` | String(96) PK | 如 `policy`、`school-rules`、`teaching` |
| `name` | String(160) | 显示名，供管理端下拉 |
| `description` | Text | 适用内容，供管理员挂库时判断。单独建表是为了用外键拦住拼错的用途，否则只会静默检索不到结果 |

### `ccsdk_knowledge_library`：库（可检索单元）

| 列 | 类型 | 说明与原因 |
| --- | --- | --- |
| `ref` | String(96) PK | 稳定引用，出现在 Run 快照中 |
| `name` | String(160) | 显示名，检索结果中返回给模型作出处 |
| `connection_ref` | FK → connection | 所属连接，学校身份由此继承 |
| `purpose_ref` | FK → purpose | 一库一用途。首期不支持一个库服务多个用途，确有需要时改为库与用途的多对多关联表 |
| `external_id` | String(255) | 供应商侧的库 ID，WeKnora 为 `kb_id` |
| `config` | JSON | 库级供应商参数，如 WeKnora 的 `tag_ids`；无则为 `{}` |
| `enabled` | Boolean | 是否参与解析 |

约束：`(connection_ref, external_id)` 唯一，防止同一外部库重复登记。

### `ccsdk_capability_knowledge`：能力与用途的关联

| 列 | 类型 | 说明与原因 |
| --- | --- | --- |
| `capability_ref` | FK → capability，PK | 所属能力 |
| `ref` | FK → purpose，PK | 用途引用，命名与其他 `ccsdk_capability_*` 关联表一致 |
| `required` | Boolean | `true` 时本校没有该用途的可用库则 Run 直接失败；`false` 时缺库只是少一类来源 |

### 不进这四张表的内容

- WeKnora 开通账号的 JWT：它是所有学校空间的 Owner，只放 Java 开通服务的私有配置。Runtime 库只存只读凭据，整库泄露也写不进、删不掉任何学校的文档。
- `ingest` Key：写入文档由 Java 管理端负责。
- WeKnora 的模型配置和存储配额：开通空间时在 WeKnora 侧设定。

## 每 Run 解析

1. 从 Java 透传的业务 Token 解析 `tenantId`，与数据库 `self` 用同一逻辑（`python/data_access/context.py`）；缺失或非法时拒绝。
2. 读取能力关联的用途。
3. 选出可用库：库启用、连接启用、连接的 `tenant_id` 是本校或 `*`，且库的用途在第 2 步结果中。
4. 有 `required=true` 的用途没有可用库时，Run 在调用模型前失败。
5. 按连接分组，每个连接调用一次适配器，该连接下的 `external_id` 一次传入。各连接分别取前 N 条，按来源分组返回给模型综合，不跨连接按分数统一排序：不同空间的重排模型、阈值和检索配置可能不同，分数不可比。确需全局排序时另行设计统一重排。

解析结果在 Run 内固定，与[配置中心](runtime-config-center.md)的逐 Run 读取规则一致。Run 记录保存解析出的库 `ref`、`external_id`，以及每条检索结果的[引用快照](#引用与出处)；用户、学校和能力由 Run 本身关联，不记录凭据。WeKnora 只看到机器 Key，不知道 `userCode`，首期不按用户隔离。

## 模型可见工具

- `knowledge_search(query, purpose?, limit?)`：`purpose` 只能取本 Run 已解析的用途，省略时检索全部已解析库。
- `knowledge_read(ref)`：读取一条检索结果对应的单个分块全文。

返回字段与供应商无关：`ref`、库名、文档标题、位置、片段、分数。`ref` 是 Run 内短编号（`k1`、`k2`…），同一分块在本 Run 重复命中时复用同一编号，内部映射到分块 ID；模型看不到分块 ID、连接和 Key。位置是适配器生成的可读描述，如“第 3 页”“第 12 段”，无定位信息时为空。

## 引用与出处

目标：对话回答中的每条知识依据都能追溯到“文档名 + 文档内位置 + 引用原文”，历史消息不依赖 WeKnora 中的文档当前状态。

1. **模型标注**：对话正文在依据句后写 `[^k1]`，可连写多个。撰写的文稿按所选指南的引用格式写文档名和位置，不使用该标记。
2. **快照**：每次检索时 Runtime 为每个新 `ref` 生成引用快照并写入 Run 记录。服务端字段：`ref`、库 `ref`、供应商文档 ID 和分块 ID、文档标题、分块序号、归一化位置、可读位置、引用原文。引用原文优先取定位信息中的 `quote`，否则截取分块正文，最多 300 字。
3. **推送与持久化**：快照通过 SSE 事件 `knowledge.sources` 推送（落地时登记到 [Runtime 接口 SSE 模块](ccsdk-runtime-interface.md#5-sse-事件模块)），对外只含 `ref`、库名、文档标题、可读位置和引用原文，不含供应商 ID。Java 按 messageId 把正文实际引用到的条目与消息一起保存；历史消息只读这份保存结果，不回查 WeKnora。文档之后被修改或删除，旧回答仍显示引用时的原文。
4. **前端展示**：把 `[^kN]` 渲染为可展开的出处，显示“文档名 · 位置”和引用原文。找不到对应快照的标记不渲染。

位置精度取决于文件类型和 WeKnora 解析结果（`source_locators`，v0.9.1 源码核对）：Word 为正文第几个段落或表格，PPT 为第几页幻灯片及标题，Excel/CSV 为工作表及起止行，md/txt 为字符起止位置，PDF 为页码及页面区域。PDF 页码只有 MinerU、PaddleOCR 等版面解析器生成，默认解析器未核实。

定位信息为空或标记 `partial` 时只显示文档名和引用原文，不编造位置。点开原文并定位到段落不在首期：需由服务端按 runId 加 `ref` 校验学校后代理 WeKnora `GET /api/v1/knowledge/:id/preview`，该接口未实测。

## 适配器

`KnowledgeProvider` 协议提供三个方法，实现放 `python/knowledge/providers/<provider>.py`，注册在 `PROVIDERS = {'weknora': WeKnoraProvider()}`：

| 方法 | 用途 |
| --- | --- |
| `validate(connection_config, library_config)` | 管理端保存时校验 `credentials`、`config` 结构，失败按现有规则返回 400 并整笔回滚 |
| `search(connection, libraries, query, limit)` | WeKnora 对应 `POST /api/v1/knowledge-search`；把结果的 `source_locators` 归一化为通用位置和可读位置 |
| `read(connection, chunk_id)` | WeKnora 对应 `GET /api/v1/chunks/by-id/:id`；`GET /api/v1/chunks/:knowledge_id` 会列出整份文档的分块，不用于单块读取 |

两个 WeKnora 接口都只需要 `retrieve` 权限。换供应商时，同样是 Key 加库 ID 模式的只需新增适配器并改取值，不改表；需要额外检索参数的放进连接或库的 `config`；需要逐用户 OAuth 凭据的必须按 REQ-001 逐 Run 注入，需另行设计。

## 规模参考（200 所学校）

约 201 个连接、800 个库、十几条用途、几十条能力关联；WeKnora 侧 Key 约 400 把（每空间一读一写）。WeKnora 默认每空间存储配额 10 GiB，全部用满约 2 TiB，建议开通时下调默认配额。检索接口没有全局限流，压力须由每 Run 预算控制。
