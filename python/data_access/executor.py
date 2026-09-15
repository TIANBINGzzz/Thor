"""Shared fixed/dynamic query service. No model-selected credentials or tenant."""

from contextlib import nullcontext
from datetime import datetime, timezone
from secrets import token_urlsafe
import json

from jsonschema import Draft202012Validator, FormatChecker
from sqlalchemy import text

from .access import domain_policy, resolve_data_access
from .catalog import Catalog, search_score
from .connections import Connections, resolve_connection
from .context import DataError, fingerprint
from .results import Results, json_value
from .sql_policy import validate_sql


def validate_parameters(parameters, definitions):
    schema = {"type": "object", "additionalProperties": False,
              "properties": {k: {a: b for a, b in v.items() if a != "required"}
                             for k, v in definitions.items()},
              "required": [k for k, v in definitions.items() if v.get("required")]}
    if next(Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(parameters), None):
        raise DataError("PARAMETERS_INVALID")
    if parameters.get("start_date") and parameters.get("end_date") and parameters["start_date"] >= parameters["end_date"]:
        raise DataError("PARAMETERS_INVALID")


class Executor:
    def __init__(self, context, config, env, config_base, catalog=None, source_keys=()):
        from copy import deepcopy
        self.context, self.config = context, deepcopy(config)
        self.catalog = (catalog or Catalog()).freeze(source_keys)
        self.source_keys = tuple(source_keys)
        self.connections = Connections(env, config_base)
        self.results = Results(context)
        self.scopes, self.entities = {}, {}
        self._versions = {s: self.catalog.revision(s) for s in self.source_keys}

    def access(self, source_key):
        self.connections.check()
        if source_key not in self.source_keys:
            raise DataError("SOURCE_FORBIDDEN")
        source = self.catalog.source(source_key)
        policy = resolve_data_access(self.context, source, self.config)
        connection = resolve_connection(self.context, source, self.config)
        return source, policy, connection

    def list_data_sources(self):
        result = []
        for source_key in self.source_keys:
            try:
                source, policy, _ = self.access(source_key)
            except DataError:
                continue
            result.append({"source_key": source_key, "name": source["name"],
                           "domains": [d for d in source["profiles"] if d in policy["domains"]],
                           "scope": policy["project_scope"]["mode"]})
        return {"sources": result}

    def describe_data_source(self, source_key, domain, topics=None):
        source, policy, _ = self.access(source_key)
        allowed = domain_policy(policy, domain)
        _, catalog = self.catalog.domain(source_key, domain)
        return {"source_key": source_key, "name": source["name"], "domain": domain,
                "tables": allowed["tables"], "functions": allowed["functions"],
                "dynamic_sql_enabled": policy.get("dynamic_sql_enabled", False),
                "topics": list(catalog.get("documents", {})),
                "documents": self.catalog.documents(source_key, domain, topics)}

    def find_query_specs(self, source_key, domain, intent=None, metric_key=None):
        _, policy, _ = self.access(source_key)
        allowed = domain_policy(policy, domain)
        _, catalog = self.catalog.domain(source_key, domain)
        if not intent and not metric_key:
            raise DataError("SEARCH_REQUIRED")
        matches = []
        for entry in catalog["queries"]:
            if entry["id"] not in allowed.get("queries", []):
                continue
            spec = self.catalog.spec(source_key, domain, entry["id"])
            output = [v for v in spec["output"] if v.get("visibility") != "internal_only"]
            if metric_key and not any(metric_key == f"{spec['id']}.{v['name']}" for v in output):
                continue
            score = search_score(spec, intent) if intent else 1
            if not score:
                continue
            matches.append((score, {**entry, "parameters": {k: v for k, v in spec["parameters"].items()
                             if not v.get("origin", "").startswith("authorized_")},
                            "output": output, "semantics": spec.get("semantics", []),
                            "blockers": spec.get("blockers", [])}))
        matches.sort(key=lambda item: (-item[0], item[1]["id"]))
        return {"queries": [item for _, item in matches[:50]], "has_more": len(matches) > 50}

    def scope(self, source_key, domain, reference):
        _, policy, _ = self.access(source_key)
        domain_policy(policy, domain)
        scope = self.scopes.get(reference)
        if (not scope or scope["source_key"] != source_key or scope["domain"] != domain
                or scope["access"] != policy["fingerprint"]):
            raise DataError("SCOPE_FORBIDDEN")
        return scope

    def _scope_ref(self, source_key, domain, project_id, policy):
        reference = "scope_" + token_urlsafe(18)
        self.scopes[reference] = {"source_key": source_key, "domain": domain,
                                  "project_id": project_id, "access": policy["fingerprint"]}
        return reference

    def resolve_entities(self, source_key, domain, entity_type, query, parent_ref=None, parameters=None):
        _, policy, connection = self.access(source_key)
        if entity_type == "school":
            if policy["project_scope"]["mode"] != "all_school":
                raise DataError("SCOPE_FORBIDDEN")
            return {"candidates": [{"name": "已授权学校范围", "scope_ref": self._scope_ref(source_key, domain, None, policy)}]}
        root, catalog = self.catalog.domain(source_key, domain)
        definition = catalog.get("entities", {}).get(entity_type)
        if not definition:
            raise DataError("ENTITY_UNSUPPORTED")
        if entity_type in {"project", "task_project"}:
            projects = policy["project_scope"].get("project_ids", [None])
        else:
            projects = [self.scope(source_key, domain, parent_ref)["project_id"]]
        candidates = []
        with self.connections.snapshot(connection) as db:
            for project in projects:
                params = dict(parameters or {})
                spec = self.catalog.spec(source_key, domain, definition["query_id"])
                if "name_pattern" in spec["parameters"]:
                    params["name_pattern"] = f"%{query}%" if query else None
                rows, complete = self._fixed_rows(source_key, domain, spec, params, project, {}, db, set())
                if not complete:
                    raise DataError("RESULT_INCOMPLETE")
                for row in rows:
                    name = row.get(definition["name_field"])
                    if query and query.casefold() not in str(name).casefold():
                        continue
                    if len(candidates) >= 100:
                        raise DataError("ENTITY_SEARCH_TOO_BROAD")
                    reference = "entity_" + token_urlsafe(18)
                    self.entities[reference] = {"source_key": source_key, "domain": domain,
                        "project_id": row.get("project_id", project), "value": row[definition["id_field"]],
                        "parameter": definition["parameter"], "access": policy["fingerprint"]}
                    item = {"name": name, "entity_ref": reference}
                    if entity_type in {"project", "task_project"}:
                        item["scope_ref"] = self._scope_ref(source_key, domain, row[definition["id_field"]], policy)
                    for field in definition.get("context_fields", []):
                        item[field] = row.get(field)
                    candidates.append(item)
        return {"candidates": candidates, "status": "no_data" if not candidates else
                "ambiguous" if len(candidates) > 1 else "resolved"}

    def _fixed_rows(self, source_key, domain, spec, parameters, project, entity_refs, db, stack):
        _, policy, connection = self.access(source_key)
        allowed = domain_policy(policy, domain, spec["id"])
        if spec["status"] != "defined":
            raise DataError("QUERY_DEFINITION_MISSING")
        if spec["id"] in stack:
            raise DataError("DEPENDENCY_CYCLE")
        definitions = spec["parameters"]
        public = {k: v for k, v in definitions.items() if not v.get("origin", "").startswith("authorized_")}
        validate_parameters(parameters, public)
        values = dict(parameters)
        if set(entity_refs) - set(definitions):
            raise DataError("ENTITY_FORBIDDEN")
        for name, definition in definitions.items():
            if definition.get("origin") == "authorized_context":
                if name != "tenant_id":
                    raise DataError("PARAMETERS_INVALID")
                values[name] = policy["business_tenant_id"]
            elif definition.get("origin") == "authorized_resolution":
                values[name] = project if name == "project_id" else None
                if name in entity_refs:
                    entity = self.entities.get(entity_refs[name])
                    if (not entity or entity["source_key"] != source_key or entity["domain"] != domain
                            or entity["parameter"] != name or entity["project_id"] != project
                            or entity["access"] != policy["fingerprint"]):
                        raise DataError("ENTITY_FORBIDDEN")
                    values[name] = entity["value"]
        validate_parameters(values, definitions)
        for dependency in spec.get("requires_queries", []):
            child = self.catalog.spec(source_key, domain, dependency)
            params = {k: v for k, v in parameters.items() if k in child["parameters"]}
            rows, complete = self._fixed_rows(source_key, domain, child, params, project, {}, db, stack | {spec["id"]})
            if not complete:
                raise DataError("DEPENDENCY_INCOMPLETE")
            for check in spec.get("checks", []):
                if check["query_id"] != dependency:
                    continue
                if check["type"] != "all_rows" or not rows or any(
                    any(row.get(k) not in choices for k, choices in check["allowed"].items()) for row in rows
                ):
                    raise DataError("DEPENDENCY_CHECK_FAILED")
        sql = self.catalog.sql(source_key, domain, spec)
        validate_sql(sql, allowed)
        return self._rows(db, sql, values, connection, spec["output"])

    def _rows(self, db, sql, values, connection, output=None):
        self.connections.check()
        limit = max(1, min(int(connection.get("max_rows", 10000)), 100000))
        statement = text(sql)
        if set(statement.compile().params) != set(values):
            raise DataError("PARAMETERS_INVALID")
        result = db.execution_options(stream_results=True).execute(statement, values)
        try:
            columns = list(result.keys())
            if len(columns) != len(set(columns)) or (output is not None and columns != [f["name"] for f in output]):
                raise DataError("OUTPUT_CONTRACT_MISMATCH")
            rows = []
            byte_count = 0
            for row in result.mappings():
                self.connections.check()
                if len(rows) == limit:
                    return rows, False
                value = dict(row)
                byte_count += len(json.dumps(value, default=json_value, ensure_ascii=False).encode())
                if byte_count > 10_000_000:
                    raise DataError("RESULT_LIMIT")
                rows.append(value)
            return rows, True
        finally:
            result.close()

    def execute_query_spec(self, source_key, domain, query_id, parameters, scope_ref, entity_refs=None, *, db=None):
        source, policy, connection = self.access(source_key)
        scope = self.scope(source_key, domain, scope_ref)
        spec = self.catalog.spec(source_key, domain, query_id)
        with (nullcontext(db) if db is not None else self.connections.snapshot(connection)) as active:
            rows, complete = self._fixed_rows(source_key, domain, spec, parameters,
                                              scope["project_id"], entity_refs or {}, active, set())
        metadata = {"source_key": source_key, "domain": domain, "query_id": query_id,
                    "query_version": spec["version"], "asset_revision": self._versions[source_key],
                    "scope_ref": scope_ref, "parameters": parameters, "access": policy["fingerprint"],
                    "connection_revision": connection["revision"], "source_version": source["version"],
                    "collected_at": datetime.now(timezone.utc).isoformat(), "complete": complete, "dynamic": False}
        reference = self.results.save(rows, metadata, spec["output"])
        return self.results.page(reference)

    def execute_readonly_sql(self, source_key, domain, sql, parameters, purpose, scope_ref):
        _, policy, connection = self.access(source_key)
        scope = self.scope(source_key, domain, scope_ref)
        allowed = domain_policy(policy, domain)
        # Deployment attests that the account/views enforce the entire policy
        # scope. Model WHERE clauses are never used as an authorization boundary.
        if (policy.get("dynamic_sql_enabled") is not True
                or connection.get("database_scope_enforced") is not True
                or connection.get("scope_policy_ref") != self.catalog.source(source_key)["policy_ref"]
                or connection.get("scope_policy_revision") != policy["revision"]):
            raise DataError("DYNAMIC_SQL_FORBIDDEN")
        selected = policy["project_scope"].get("project_ids", [])
        if not ((policy["project_scope"]["mode"] == "all_school" and scope["project_id"] is None)
                or (len(selected) == 1 and scope["project_id"] == selected[0])):
            raise DataError("DYNAMIC_SCOPE_NOT_ENFORCED")
        if any(isinstance(v, (dict, list)) for v in parameters.values()) or len(parameters) > 100:
            raise DataError("PARAMETERS_INVALID")
        tree = validate_sql(sql, allowed, dynamic=True)
        names = [selection.alias_or_name for selection in tree.selects]
        if any(not name for name in names) or len(names) != len(set(names)):
            raise DataError("OUTPUT_ALIAS_REQUIRED")
        output = [{"name": name} for name in names]
        with self.connections.snapshot(connection) as db:
            rows, complete = self._rows(db, sql, parameters, connection, output)
        reference = self.results.save(rows, {"source_key": source_key, "domain": domain,
            "access": policy["fingerprint"], "connection_revision": connection["revision"],
            "scope_ref": scope_ref, "complete": complete, "dynamic": True,
            "asset_revision": self._versions[source_key],
            "collected_at": datetime.now(timezone.utc).isoformat(),
            "parameters": parameters, "purpose": purpose, "sql_fingerprint": fingerprint(sql)}, output)
        return self.results.page(reference)
