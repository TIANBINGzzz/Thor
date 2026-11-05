"""Static deployment policies, resolved independently for each source."""

from copy import deepcopy

from .context import DataError, fingerprint


def resolve_data_access(context, source, config, catalog):
    """按可信身份校验来源授权，并生成包含表白名单的独立策略副本。"""
    policy = deepcopy(config['policy'])
    if (policy.get("source_key") != source["source_key"]
            or context.capability_ref not in policy.get("capabilities", [])):
        raise DataError("SOURCE_FORBIDDEN")
    tenants = policy.get('tenant_id')
    if (not isinstance(tenants, list) or not tenants
            or any(not isinstance(t, str) or not t.strip() or t in {'*', 'default'} for t in tenants)):
        raise DataError('CONFIG_INVALID')
    resolved = []
    for tenant in tenants:
        if tenant == 'self':
            tenant = context.data_tenant_id
            if not tenant:
                raise DataError('BUSINESS_IDENTITY_REQUIRED')
        if tenant not in resolved:
            resolved.append(tenant)
    policy['authorized_tenants'] = resolved
    if context.template_key and context.template_key not in policy.get("templates", []):
        raise DataError("TEMPLATE_FORBIDDEN")
    scope = policy.get("project_scope", {})
    if scope.get("mode") == "selected":
        ids = scope.get("project_ids")
        if not isinstance(ids, list) or not ids or any(not isinstance(x, str) or not x for x in ids):
            raise DataError("SCOPE_REQUIRED")
    elif scope.get("mode") != "all_school":
        raise DataError("SCOPE_REQUIRED")
    for domain, allowed in policy.get('domains', {}).items():
        schema = catalog.schema(source['source_key'], domain)
        tables = allowed['tables']
        if not isinstance(tables, list) or not set(tables) <= schema['tables'].keys():
            raise DataError('DOMAIN_FORBIDDEN')
        allowed.update(tables={name:schema['tables'][name] for name in tables},
                       functions=schema['functions'], internal_columns=schema.get('internal_columns', []),
                       tenant_column=schema.get('tenant_column'))
        if not allowed['tenant_column'] or any(allowed['tenant_column'] not in columns
                                              for columns in allowed['tables'].values()):
            raise DataError('TENANT_SCOPE_NOT_ENFORCED')
    policy["fingerprint"] = fingerprint(policy)
    return policy


def domain_policy(policy, domain, query_id=None):
    """取得获准业务域策略，并按需检查固定查询权限。"""
    domain = policy.get("domains", {}).get(domain)
    if not domain:
        raise DataError("DOMAIN_FORBIDDEN")
    if query_id and query_id not in domain.get("queries", []):
        raise DataError("QUERY_FORBIDDEN")
    return domain
