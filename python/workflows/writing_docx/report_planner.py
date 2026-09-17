"""Run-owned batch snapshots; missing definitions remain explicit plan nodes."""

import asyncio
from collections import Counter
from datetime import date, timedelta
from itertools import product
import json
from secrets import token_urlsafe

from jsonschema import Draft202012Validator, FormatChecker

from data_access.context import DataError, fingerprint
from data_access.results import json_value


class ReportPlanner:
    def __init__(self, services, template):
        self.services, self.template = services, template
        self.plans = {}
        self.tasks = set()
        self.latest = None

    async def prepare(self, report_parameters, scope_refs, dataset_keys=None):
        executor = self.services.current()
        if next(Draft202012Validator(self.template["parameters"], format_checker=FormatChecker()).iter_errors(report_parameters), None):
            raise DataError("REPORT_PARAMETERS_INVALID")
        years = report_parameters["years"]
        if report_parameters["period_mode"] == "annual" and len(years) != 1:
            raise DataError("REPORT_PERIOD_AMBIGUOUS")
        as_of = report_parameters.get("as_of")
        if as_of and (as_of < min(years) + "-01-01" or as_of > max(years) + "-12-31"):
            raise DataError("REPORT_PERIOD_AMBIGUOUS")
        if set(scope_refs) != set(self.template["scope_roles"]):
            raise DataError("SCOPE_REQUIRED")
        for role, names in self.template["scope_roles"].items():
            if set(scope_refs[role]) != set(names):
                raise DataError("SCOPE_REQUIRED")
            source_key = self.template["source_roles"][role]
            for ref in scope_refs[role].values():
                executor.scope(source_key, role, ref)
        available = {item['dataset_key'] for item in self.template['_bindings']['datasets']}
        selected = sorted(available if dataset_keys is None else set(dataset_keys))
        if not set(selected) <= available:
            raise DataError('DATASET_INVALID')
        evidence_scopes = [dict(source_key=source, domain=domain, scope_ref=ref, scope_role=scope_role)
            for role, source in self.template['source_roles'].items()
            for domain in executor.catalog.source(source)['domains']
            for scope_role, ref in scope_refs.get(role, {}).items()]
        identity = fingerprint([report_parameters, scope_refs, selected, self.template["_revision"],
                                executor._versions, executor.context.owner])
        for plan in self.plans.values():
            if plan["input_fingerprint"] == identity:
                self.latest = plan["plan_ref"]
                return self.summary(plan)
        if len(self.plans) >= 5 or any(not task.done() for task in self.tasks):
            raise DataError("PLAN_BUSY")
        reference = "plan_" + token_urlsafe(18)
        plan = {"plan_ref": reference, "plan_version": len(self.plans) + 1, "input_fingerprint": identity,
                "template_revision": self.template["version"], "template_asset_revision": self.template['_revision'],
                "writing_rules_revision": self.services.workflow_revision,
                "asset_revision": executor._versions,
                "report_parameters": report_parameters, "status": "queued", "nodes": [],
                "dataset_keys": selected, "locations": self.template['_locations'],
                "evidence_scopes": evidence_scopes, "drafts":{}, "coverage": {},
                "connection_revisions": {}, "policy_revisions": {}}
        self._compile(plan, scope_refs)
        self.plans[reference] = plan
        self.latest = reference
        task = asyncio.create_task(self._execute(plan), name="ccsdk-report-plan")
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        return self.summary(plan)

    def _compile(self, plan, scopes):
        executor = self.services.current()
        parameters = plan["report_parameters"]
        seen = {}
        for dataset in self.template["_bindings"]["datasets"]:
            if dataset['dataset_key'] not in plan['dataset_keys']:
                continue
            source_key = self.template["source_roles"][dataset["source_role"]]
            _, policy, connection = executor.access(source_key)
            plan["connection_revisions"][source_key] = connection["revision"]
            plan["policy_revisions"][source_key] = policy["revision"]
            domain = dataset["domain"]
            spec = executor.catalog.spec(source_key, domain, dataset["query_id"])
            values, missing = {}, False
            for name, binding in dataset["parameter_bindings"].items():
                origin = binding["from"]
                if origin == "literal":
                    values[name] = [binding["value"]]
                elif origin == "report_parameter" and binding["key"] in parameters:
                    value = parameters[binding["key"]]
                    values[name] = value if binding.get("expand") == "each" else [value]
                else:
                    missing = True
            for name, definition in spec["parameters"].items():
                if name in values or definition.get("origin", "").startswith("authorized_"):
                    continue
                # These are candidate windows, not proof of historical validity.
                if name in {"start_date", "end_date"}:
                    values[name] = [min(parameters["years"]) + "-01-01" if name == "start_date" else
                                   (date.fromisoformat(parameters.get("as_of", max(parameters["years"]) + "-12-31")) + timedelta(days=1)).isoformat()]
                else:
                    missing = True
            if dataset.get("depends_on"):
                missing = True  # No implicit prior-result expression evaluation.
            for combination in product(*values.values()):
                bound = dict(zip(values, combination))
                scope_ref = scopes[dataset["source_role"]][dataset["scope_role"]]
                signature = fingerprint([source_key, domain, spec["id"], spec["version"], bound, scope_ref])
                if signature in seen:
                    seen[signature]["dataset_keys"].append(dataset["dataset_key"])
                    seen[signature]["scope_roles"] = sorted(set(
                        seen[signature]["scope_roles"] + [dataset["scope_role"]]))
                    continue
                node = {"node_key": signature, "source_key": source_key, "domain": domain,
                        "query_id": spec["id"], "query_version": spec["version"], "parameters": bound,
                        "scope_ref": scope_ref, "scope_roles": [dataset["scope_role"]],
                        "dataset_keys": [dataset["dataset_key"]], "result_ref": None,
                        "status": "blocked" if spec["status"] != "defined" or missing else "pending",
                        "error_code": "DEFINITION_MISSING" if spec["status"] != "defined" or missing else None,
                        "dependencies": spec.get("requires_queries", []), "attempts": 0}
                seen[signature] = node
                plan["nodes"].append(node)
        if len(plan["nodes"]) > 500:
            raise DataError("PLAN_LIMIT")

    async def _execute(self, plan):
        try:
            plan["status"] = "running"
            async with asyncio.timeout(600):
                await self.services.call(self._snapshots, plan)
            self._coverage(plan)
            plan["status"] = "ready"
        except asyncio.CancelledError:
            plan["status"] = "cancelled"
            raise
        except Exception as error:
            plan["status"] = "failed"
            plan["error_code"] = error.code if isinstance(error, DataError) else "EXECUTION_FAILED"
        finally:
            for node in plan["nodes"]:
                if node["status"] in {"pending", "running"}:
                    node["status"] = "cancelled" if plan["status"] == "cancelled" else "failed"
            self._save(plan)

    def _snapshots(self, plan):
        executor = self.services.current()
        for source_key in sorted({n["source_key"] for n in plan["nodes"] if n["status"] == "pending"}):
            _, _, connection = executor.access(source_key)
            nodes = [n for n in plan["nodes"] if n["source_key"] == source_key and n["status"] == "pending"]
            try:
                with executor.connections.snapshot(connection) as db:
                    for node in nodes:
                        executor.connections.check()
                        node["status"], node["attempts"] = "running", 1
                        try:
                            result = executor.execute_query_spec(source_key, node["domain"], node["query_id"],
                                node["parameters"], node["scope_ref"], db=db)
                            node["result_ref"] = result["result_ref"]
                            node["status"] = "succeeded" if result["complete"] else "blocked"
                            if not result["complete"]:
                                node["error_code"] = "RESULT_INCOMPLETE"
                        except DataError as error:
                            if error.code in {"QUERY_DEFINITION_MISSING", "DEPENDENCY_CHECK_FAILED", "DEPENDENCY_INCOMPLETE"}:
                                node["status"], node["error_code"] = "blocked", error.code
                            else:
                                raise
            except Exception:
                # No partial source snapshot remains eligible for rendering.
                for node in nodes:
                    node["status"], node["result_ref"] = "failed", None
                raise

    def _coverage(self, plan):
        recommended = {item['location_hint'] for item in plan['locations']
                       if item.get('annotation', {}).get('node_type') in {'scalar', 'narrative'}}
        plan['coverage'] = {'edited_locations': len(plan['drafts']),
                            'recommended_locations': len(recommended),
                            'unedited_recommendations': len(recommended - set(plan['drafts'])),
                            'usage': 'advisory_not_completion_proof'}

    def _save(self, plan):
        directory = self.services.current().context.run_directory / "report"
        directory.mkdir(parents=True, exist_ok=True)
        (directory / f"{plan['plan_ref']}.json").write_text(json.dumps(plan, ensure_ascii=False, default=json_value), encoding="utf-8")

    def summary(self, plan):
        return {k: plan[k] for k in ("plan_ref", "plan_version", "status", "coverage")}

    def get(self, plan_ref, section_key=None, cursor=None, writing_only=False):
        plan = self.plans.get(plan_ref)
        if plan is None:
            raise DataError("PLAN_FORBIDDEN")
        self._coverage(plan)
        sections = list(dict.fromkeys(s['section_key'] for s in plan['locations']))
        result = {**self.summary(plan), "sections": sections,
                  "map_status": self.template['_map_status'], "warnings": self.template['_warnings'],
                  "drafts_saved":len(plan.get('drafts',{})),
                  "progress": dict(Counter(n["status"] for n in plan["nodes"]))}
        if section_key is None:
            return result
        if plan["status"] != "ready":
            return result
        if section_key not in sections:
            raise DataError("SECTION_INVALID")
        offset = 0
        if cursor is not None:
            saved = plan.get("cursors", {}).get(cursor)
            if not saved or saved[0] != section_key or saved[2] != writing_only:
                raise DataError("CURSOR_INVALID")
            offset = saved[1]
        from .report_locations import public_location
        locations = [{**public_location(item), 'draft_saved': item['location_hint'] in plan['drafts']}
                     for item in plan['locations'] if item['section_key'] == section_key
                     and (not writing_only or item.get('annotation', {}).get('node_type') != 'static')]
        next_cursor = None
        if offset + 50 < len(locations):
            next_cursor = "cursor_" + token_urlsafe(18)
            plan.setdefault("cursors", {})[next_cursor] = (section_key, offset + 50, writing_only)
        result.update({"location_hints": locations[offset:offset+50], "cursor": next_cursor,
                       "facts": [{"query_id": n["query_id"], "parameters": n["parameters"],
                                  "dataset_keys": n['dataset_keys'],
                                  "scope_roles": n["scope_roles"],
                                  "status": n["status"], "result_ref": n["result_ref"],
                                  "error_code": n["error_code"], "usage": "candidate_facts_require_period_validation"}
                                 for n in plan["nodes"]]})
        return result

    async def render(self, plan_ref, section_drafts):
        from .report_renderer import render
        if plan_ref != self.latest or plan_ref not in self.plans:
            raise DataError("PLAN_SUPERSEDED")
        plan = self.plans[plan_ref]
        if plan["status"] != "ready":
            raise DataError("PLAN_NOT_READY")
        from .report_renderer import validate_drafts
        drafts = {**plan.get('drafts', {}), **validate_drafts(plan, section_drafts, self.services.current())}
        output=await self.services.call(render, self.template, plan, list(drafts.values()), self.services.current())
        plan['drafts']=drafts
        self._coverage(plan)
        plan['rendered']=output
        plan.pop('validation',None)
        self._save(plan)
        return output

    def save_drafts(self, plan_ref, section_drafts):
        if plan_ref != self.latest:
            raise DataError('PLAN_SUPERSEDED')
        plan=self.plans[plan_ref]
        if plan['status'] != 'ready':
            raise DataError('PLAN_NOT_READY')
        from .report_renderer import validate_drafts
        plan.setdefault('drafts', {}).update(validate_drafts(plan, section_drafts, self.services.current()))
        plan.pop('rendered',None)
        plan.pop('validation',None)
        self._coverage(plan)
        self._save(plan)
        return {'saved':len(plan['drafts']), 'coverage':plan['coverage']}

    async def close(self):
        for task in list(self.tasks):
            task.cancel()
        if self.tasks:
            await asyncio.gather(*list(self.tasks), return_exceptions=True)
