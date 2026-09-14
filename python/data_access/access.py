"""Static single-tenant policies, resolved independently for each source."""

from copy import deepcopy

from .context import DataError, fingerprint


def resolve_data_access(context, source, config):
    policy = deepcopy(config.get("policies", {}).get(source["policy_ref"], {}))
    if (policy.get("source_key") != source["source_key"]
            or policy.get("tenant_id") != context.tenant_id
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
    policy["fingerprint"] = fingerprint(policy)
    return policy


def domain_policy(policy, domain, query_id=None):
    domain = policy.get("domains", {}).get(domain)
    if not domain:
        raise DataError("DOMAIN_FORBIDDEN")
    if query_id and query_id not in domain.get("queries", []):
        raise DataError("QUERY_FORBIDDEN")
    return domain
