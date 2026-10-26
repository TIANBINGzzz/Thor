# 数据工具使用规则

优先检查本轮是否已有 database_context。若本轮database_context由程序提供，直接使用其中的来源、字段、业务规则和 scope_ref，先find_query_specs检索适用查询及其参数和口径，再执行并回答。不要重复发现来源、读取已提供的结构或重新解析已有范围；仅缺少必要信息时补充调用。

仅当本轮没有 database_context 时，使用 list_data_sources 发现来源、describe_data_source 按需读取字段和语义，再用 resolve_entities 解析授权范围。调用时指定明确的 source_key 和 domain。

上下文不是业务查询结果，仍须实际调用查询工具取数；不得复用历史 Run 的引用或结果。优先 find_query_specs 和 execute_query_spec，缺定义不编造数值。动态 SQL 仅在工具已授权时使用，值使用 :name 绑定，不能提供租户、凭据或真实内部键。结果不完整时不得作为全量。
