# 知识库接入契约

决策与 WeKnora 权限调研见 [ADR-040](../ADR/040-knowledge-base-integration.md)。本文是配置表、Run 内引用暂存和知识检索适配器的唯一来源。Python Runtime 已实现配置解析、WeKnora 检索/分块读取、出处事件和 24 小时暂存清理；Java 消息长期保存、前端渲染和预览代理不在本轮范围内。字段以 `python/runtime/config_store.py` 与 `python/runtime/run_store.py` 的实际定义为准。

## 设计原则

- **表不认识供应商**：列名只表达通用概念（连接、凭据、外部 ID）。供应商专属参数进 `config` JSON，由适配器在保存时校验。
- **学校归属挂在连接上**：一个连接就是一个隔离边界（WeKnora 的一个空间加一把只读 Key）。库只能属于一个连接，结构上无法把 A 校的库挂到 B 校的凭据下。
- **能力绑定用途，不绑定库**：能力声明“需要政策类、校本制度类知识”，每 Run 按本校身份把用途解析成库。新开学校只加连接和库，不改能力。
- **Runtime 只读**：配置库里只有检索权限的凭据；写入凭据和开通账号归 Java 管理端。
- **回答由现有 Loop 完成**：WeKnora 只用于检索和按 ref 读取分块，不调用 WeKnora 对话/回答流程；检索结果交给现有 Runtime Agent Loop，由模型基于结果组织答案。

## 表结构

列风格沿用现有配置表：`ref` 主键 `String(96)`，显示名 `String(160)`，秘密字段加密后存 `Text`，扩展参数存 `JSON` 对象。

### `runtime_knowledge_connection`：连接（隔离边界）

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

### `runtime_knowledge_purpose`：用途词表

| 列 | 类型 | 说明与原因 |
| --- | --- | --- |
| `ref` | String(96) PK | 如 `policy`、`school-rules`、`teaching` |
| `name` | String(160) | 显示名，供管理端下拉 |
| `description` | Text | 适用内容，供管理员挂库时判断。单独建表是为了用外键拦住拼错的用途，否则只会静默检索不到结果 |

### `runtime_knowledge_library`：库（可检索单元）

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

### 关系约束与索引

- `runtime_knowledge_library.connection_ref`、`purpose_ref` 和 `runtime_capability_knowledge` 两端外键均使用 `ON DELETE RESTRICT`；先停用再清理引用，避免删除配置时静默丢失授权关系。
- 索引：连接表 `(tenant_id, enabled)`；库表 `(connection_ref, purpose_ref, enabled)`；能力关联表按 `purpose_ref` 反向索引。四表不保留秘密明文，管理端仍通过现有配置管理鉴权读写。
- `enabled=false` 表示停用，停用连接会使其下库都不可解析；停用库或能力关联只影响对应范围。Runtime 配置库不承载 WeKnora 开通任务；Java 平台复用现有任务与对账机制，若当前没有则增加 Java 侧任务记录。管理端不新增配置版本或独立审计表。

### `runtime_capability_knowledge`：能力与用途的关联

| 列 | 类型 | 说明与原因 |
| --- | --- | --- |
| `capability_ref` | FK → capability，PK | 所属能力 |
| `ref` | FK → purpose，PK | 用途引用，命名与其他 `runtime_capability_*` 关联表一致 |
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
5. 连接决定服务地址、空间和凭据；WeKnora 首期对每个已选库调用一次 `POST /api/v1/knowledge-bases/{kb_id}/hybrid-search`。该接口每条检索结果对应一个分块；父分块和邻近分块若被返回，也是独立结果。WeKnora 的多库参数有相同 embedding model 前提，首期不依赖该前提批量检索。每库最多返回 `max_results` 条，结果按库分组给模型，不跨库或跨连接按分数统一排序。

解析结果在 Run 内固定，与[配置中心](runtime-config-center.md)的逐 Run 读取规则一致。Runtime Run 记录保存解析出的库 `ref`、`external_id` 和引用快照，并按现有 JWT `sub` 关联用户；Java 在自己的消息/Run 业务记录上保存已认证的 `userCode`，供审计使用，不参与授权或检索。若它与现有用户字段不同，只扩展该业务记录，不新增知识库专属表，也不传给 Runtime、模型或 WeKnora。WeKnora 只看到机器 Key，首期不按用户隔离。

## 模型可见工具

- `knowledge_search(query, purpose?, limit?)`：`purpose` 只能取本 Run 已解析的用途，省略时检索全部已解析库。
- `knowledge_read(ref)`：读取一条检索结果对应的单个分块全文。

返回字段与供应商无关：`ref`、库名、文档标题、位置、片段、分数。`ref` 是本 Run 内短编号（`k1`、`k2`…），代表模型看到的一条检索结果，首期对应一个 WeKnora 分块；`knowledge_read(ref)` 返回该分块全文。同一分块本 Run 重复命中时复用编号，去重键为 `(connection_ref, external_library_id, chunk_id)`，避免不同 WeKnora 实例或知识库的 ID 撞号。模型看不到这些 ID、连接和 Key。一个分块可有多个 `source_locators`，表示该分块跨越多个段落、页面或其他原文位置，不表示结果合并了多个分块。若 Runtime 将来主动合并相邻分块，`ref` 表示合并后的结果，位置集合取各分块位置的并集。

## 引用与出处

目标：对话回答中的每条知识依据都能追溯到“文档名 + 文档内位置 + 引用原文”，历史消息不依赖 WeKnora 中的文档当前状态。

1. **模型标注**：对话正文在依据句后写 `[^k1]`，可连写多个。撰写的文稿按所选指南的引用格式写文档名和位置，不使用该标记。前端只把已登记且位于普通 Markdown 正文中的标记解析为引用；代码块、行内代码中的同形文本不是引用。
2. **Run 内快照**：Runtime 为新 `ref` 保存内部来源记录和对外快照。内部记录含 `(run_id, ref)`、`connection_ref`、`library_ref`、`external_library_id`、WeKnora 文档 ID、分块 ID、`chunk_index` 和规范化位置；不保存 Key 或未使用的原始 locator 字段。来源唯一键为 `(run_id, connection_ref, external_library_id, chunk_id)`。
3. **对外快照结构**：每个 `ref` 含 `libraryName`、`documentTitle`、`excerpt`、`excerptTruncated`、`sources[]` 和 `moreLocations`。`documentTitle` 优先取 `knowledge_title`，为空时回退 `knowledge_filename`。`sources[]` 每项对应一个位置，含 `type`、`label`、`partial`、`quote`、`quoteTruncated`，以及按类型可用的 `page`、`bbox`、`block`、`slide`、`sheet`、`rowStart`、`rowEnd`、`start`、`end`、`startMs`、`endMs`、`section`。`bbox` 保留 WeKnora 归一化坐标；结构化位置随快照保存，供后续预览使用。每个 `quote` 最多 300 个 Unicode 码点，超出截断并置 `quoteTruncated=true`；每个 `ref` 最多发送 5 个位置，其余数量记入 `moreLocations`。`excerpt` 是无定位时展示的分块正文摘录，同样最多 300 个 Unicode 码点并带截断标记。无定位时 `sources=[]`。`partial=true` 的位置不显示 `label`，只显示文档名和引用原文，不把不完整映射描述成确定位置。首期不做内容脱敏：`excerpt`、`quote` 和 `knowledge_read` 返回 WeKnora 原文，仅做长度截断及字段归一化；公共事件不暴露供应商内部 ID 或凭据。
4. **PDF 位置**：WeKnora v0.9.1 的内置解析器也提供页码；文本页通常有区域框，扫描页只有页码，区域框随解析结果而异。文本页区域框默认由 `DOCREADER_PDF_SOURCE_BOXES` 开启。Word locator 的 `block` 是正文段落和表格的序号；PPT 使用幻灯片序号及标题；Excel/CSV 使用工作表和行范围；md/txt 使用字符偏移。统一保留结构化字段原值，不自行改写偏移边界。
5. **事件与消息保存**：Runtime 通过 `knowledge.sources` SSE 事件推送归一化快照，不含供应商文档 ID、分块 ID、`source_id`、`source_hash` 或 Key。事件及重放规则见 [Runtime 接口 SSE 模块](ccsdk-runtime-interface.md#5-sse-事件模块)。事件仍受原 Run 的租户、用户授权保护，不得跨 Run 转发或缓存。Java 按 Run 缓存事件，并在 `run.completed` 后用最终正文过滤实际引用的 `ref`，将这些公开快照和回答一并写入现有消息 `retrieverResources` 字段；不新增引用关系表。消息是长期引用快照的唯一权威副本，历史展示不回查 WeKnora。
6. **前端展示**：将已匹配的 `[^kN]` 渲染为可展开出处，显示“文档名 · 位置”和引用原文；无位置时显示文档名和摘录。正文标记找不到对应快照时不渲染为引用。文档后来修改或删除，不改变历史消息快照。`quote`、`excerpt` 和标题均为不可信文档内容，必须按文本安全转义，不作为 HTML 渲染。

点开原文并定位到段落不在首期。未来预览必须经服务端代理并按 Run 的租户与连接授权；当前预览路由尚未实测。因 Runtime 来源映射终态后只保留 24 小时，长期预览若需继续支持，须另行设计长期授权的文档标识映射，不能依赖已清理的 Run 内 `ref`。

### RunStore 暂存表（Runtime 本地 SQLite）

新增 `run_knowledge_sources`，与 MySQL 中四张配置表分开：

| 列 | SQLite 类型 | 说明 |
| --- | --- | --- |
| `run_id` | TEXT | 所属 Run，外键关联 `runs`，删除 Run 时级联 |
| `ref` | TEXT | 模型可见的本 Run 短编号，如 `k1` |
| `connection_ref` / `library_ref` | TEXT | 私有配置引用，不对外发送 |
| `external_library_id` | TEXT | 供应商库 ID，仅 Runtime 内部使用 |
| `knowledge_id` / `chunk_id` | TEXT | WeKnora 文档 ID、分块 ID，仅用于定位和 `knowledge_read` |
| `chunk_index` | INTEGER | 分块序号，可空 |
| `snapshot_json` | TEXT | 规范化位置和有界公开快照；不保存 Key 或完整分块正文 |
| `created_at` / `updated_at` | INTEGER | Unix 毫秒时间 |

主键为 `(run_id, ref)`；唯一约束 `(run_id, connection_ref, external_library_id, chunk_id)` 保证稳定去重。`knowledge_read` 按私有映射向 WeKnora 读取全文，Run JWT 绑定的当前 Run 是查询范围，不接受模型或请求正文指定其他 Run。`userCode` 由 Java 的消息/Run 业务记录关联，不在 Runtime 来源表重复。

Runtime 不新增用户身份字段，现有 `runs.user_id` 继续记录 JWT `sub`。终态事件落库时刷新现有 `updated_at`，并建 `(status, updated_at)` 清理索引；终态事件之后不再修改 Run 记录。Runtime 单副本 SQLite 是现有部署约束；SaaS 多校共用该 Runtime，本地部署每客户一套。

RunStore 清理器按 `(status, updated_at)` 索引扫描；终态事件落库满 24 小时后，在同一事务中删除该 Run 的全部 `run_events` 和 `run_knowledge_sources`。非终态不清理。保留 `runs` 的轻量状态/会话索引、SDK transcript、工作区和 Artifact，它们分别沿用各自生命周期。Java 消息 `retrieverResources` 和用户身份关联不受 Runtime 清理影响。24 小时后 Runtime 不保证 SSE 事件重放；历史回答和出处从 Java 消息读取。清理机制属于 RunStore 通用能力，按 [Runtime 接口契约](ccsdk-runtime-interface.md#5-sse-事件模块) 实施与验收。

## 适配器

`KnowledgeProvider` 协议提供三个方法，实现放 `python/knowledge/providers/<provider>.py`，注册在 `PROVIDERS = {'weknora': WeKnoraProvider()}`：

| 方法 | 用途 |
| --- | --- |
| `validate(connection_config, library_config)` | 管理端保存时校验 `credentials`、`config` 结构，失败按现有规则返回 400 并整笔回滚 |
| `search(connection, libraries, query, limit)` | 对选中的每个 WeKnora 库调用 `POST /api/v1/knowledge-bases/{kb_id}/hybrid-search`，将单条结果映射为一个分块及其多个 `source_locators`；归一化位置并按 `(connection_ref, external_library_id, chunk_id)` 去重 |
| `read(connection, chunk_id)` | WeKnora 对应 `GET /api/v1/chunks/by-id/:id`；`GET /api/v1/chunks/:knowledge_id` 会列出整份文档的分块，不用于单块读取 |

两个 WeKnora 接口都只需要 `retrieve` 权限。换供应商时，同样是 Key 加库 ID 模式的只需新增适配器并改取值，不改表；需要额外检索参数的放进连接或库的 `config`；需要逐用户 OAuth 凭据的必须按 REQ-001 逐 Run 注入，需另行设计。

## 规模参考（200 所学校）

约 201 个连接、800 个库、十几条用途、几十条能力关联；WeKnora 侧 Key 约 400 把（每空间一读一写）。WeKnora 默认每空间存储配额 10 GiB，全部用满约 2 TiB，建议开通时下调默认配额。检索接口没有全局限流，压力须由每 Run 预算控制。
