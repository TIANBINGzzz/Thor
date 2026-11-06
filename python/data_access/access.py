"""数据范围按来源授权，self 每轮从业务 Token 解析；SQL 边界来自登记资产。"""

from .context import DataError, fingerprint


def resolve_data_access(context, source, config, catalog):
    """Run 身份只约束结果归属；数据库租户只由业务身份和可信来源配置决定。"""
    if not context.data_tenant_id:
        raise DataError('BUSINESS_IDENTITY_REQUIRED')
    tenants = config['access']['tenantIds']
    resolved = []
    for tenant in tenants:
        tenant = context.data_tenant_id if tenant == 'self' else tenant
        if tenant not in resolved:
            resolved.append(tenant)
    domains = {}
    for domain in source['domains']:
        schema = catalog.schema(source['source_key'], domain)
        _, assets = catalog.domain(source['source_key'], domain)
        allowed = {k: schema.get(k, []) for k in ('tables', 'functions', 'internal_columns')}
        allowed['tenant_column'] = schema.get('tenant_column')
        if not allowed['tenant_column'] or any(allowed['tenant_column'] not in columns
                                              for columns in allowed['tables'].values()):
            raise DataError('TENANT_SCOPE_NOT_ENFORCED')
        allowed['queries'] = [q['id'] for q in assets['queries']]
        domains[domain] = allowed
    policy = {'authorized_tenants': resolved, 'domains': domains,
              'dynamic_sql_enabled': config.get('query', {}).get('dynamic_sql_enabled', False)}
    policy['fingerprint'] = fingerprint(policy)
    return policy


def domain_policy(policy, domain, query_id=None):
    """只有已登记的业务域和指标可执行；待定义指标另由执行器拒绝。"""
    allowed = policy['domains'].get(domain)
    if not allowed:
        raise DataError('DOMAIN_FORBIDDEN')
    if query_id and query_id not in allowed['queries']:
        raise DataError('QUERY_FORBIDDEN')
    return allowed
