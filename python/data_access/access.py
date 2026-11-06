"""客户范围来自部署绑定，SQL 边界来自可信来源登记。"""

from runtime.deployment_config import deployment_section, require_tenant
from .context import DataError, fingerprint


def resolve_data_access(context, source, config, catalog):
    """同客户用户共享业务数据；不能通过 Run 或业务 Token 切换客户。"""
    try:
        require_tenant(context.tenant_id)
    except ValueError:
        raise DataError('TENANT_FORBIDDEN') from None
    tenant = deployment_section('deployment')['tenantId']
    if context.data_tenant_id is not None and context.data_tenant_id != tenant:
        raise DataError('TENANT_FORBIDDEN')
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
    policy = {'tenant_id': tenant, 'domains': domains,
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
