"""Static deployment policies, resolved independently for each source."""

from copy import deepcopy

from .context import DataError, fingerprint


def resolve_data_access(context, source, config, catalog):
    policy = deepcopy(config['policy'])
    # 部署侧显式配置 * 才共享来源；真实身份仍用于 Run 和结果归属。
    if (policy.get("source_key") != source["source_key"]
            or context.capability_ref not in source.get('capabilities', [])
            or policy.get("tenant_id") not in ("*", context.tenant_id)
            or context.capability_ref not in policy.get("capabilities", [])
            or not policy.get("revision") or not policy.get("business_tenant_id")):
        raise DataError("SOURCE_FORBIDDEN")
    users = policy.get("users", [])
    if users != "all_authenticated" and context.user_id not in users:
        raise DataError("SOURCE_FORBIDDEN")
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
                       functions=schema['functions'], internal_columns=schema.get('internal_columns', []))
    policy["fingerprint"] = fingerprint(policy)
    return policy


def domain_policy(policy, domain, query_id=None):
    domain = policy.get("domains", {}).get(domain)
    if not domain:
        raise DataError("DOMAIN_FORBIDDEN")
    if query_id and query_id not in domain.get("queries", []):
        raise DataError("QUERY_FORBIDDEN")
    return domain
