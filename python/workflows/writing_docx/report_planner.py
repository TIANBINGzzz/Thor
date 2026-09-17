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

    async def prepare(self, report_parameters, scope_refs):
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
        identity = fingerprint([report_parameters, scope_refs, self.template["_revision"],
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
                "slots": [], "drafts":{}, "coverage": {}, "connection_revisions": {}, "policy_revisions": {}}
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
            self._slots(plan)
            plan["status"] = "blocked" if plan["coverage"].get("required_missing") else "ready"
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

    def _slots(self, plan):
        executor = self.services.current()
        slots = []
        for binding in self.template["_slots"]:
            binding = {**binding}
            if binding["kind"] != "static":
                role = binding.get("scope_role", "school")
                binding["evidence_datasets"] = [
                    dataset["dataset_key"] for dataset in self.template["_bindings"]["datasets"]
                    if role == "school" or dataset["scope_role"] == role
                ]
            slot = {k: binding[k] for k in ("slot_key", "section_key", "name", "kind", "required")}
            from .report_values import resolve_value
            slot.update(resolve_value(binding, plan, executor))
            slot['scope_role'] = binding.get('scope_role', 'school')
            slot['evidence_scopes'] = [dict(zip(('source_key', 'domain', 'scope_ref'), scope))
                for scope in sorted({(n['source_key'], n['domain'], n['scope_ref']) for n in plan['nodes']
                    if set(n['dataset_keys']) & set(binding.get('evidence_datasets', []))})]
            slots.append(slot)
        plan["slots"] = slots
        counts = dict(Counter(s["value_status"] for s in slots))
        counts.update({"total": len(slots), "dynamic": sum(s["kind"] != "static" for s in slots),
                       "required_missing": sum(s["required"] and s["value_status"] not in {"filled","unavailable","awaiting_draft"} for s in slots),
                       "drafts_required":sum(s.get('draftable', False) and s['required'] for s in slots)})
        plan["coverage"] = counts

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
        sections = sorted({s["section_key"] for s in self.template["_slots"]})
        result = {**self.summary(plan), "sections": sections,
                  "writing_sections":[s for s in sections if any(v['section_key']==s and v.get('draftable') for v in plan['slots'])],
                  "drafts_saved":len(plan.get('drafts',{})),
                  "progress": dict(Counter(n["status"] for n in plan["nodes"]))}
        if section_key is None:
            return result
        if plan["status"] not in {"ready", "blocked"}:
            return result
        if section_key not in sections:
            raise DataError("SECTION_INVALID")
        offset = 0
        if cursor is not None:
            saved = plan.get("cursors", {}).get(cursor)
            if not saved or saved[0] != section_key or saved[2] != writing_only:
                raise DataError("CURSOR_INVALID")
            offset = saved[1]
        slots = [s for s in plan["slots"] if s["section_key"] == section_key and (not writing_only or s.get('draftable'))]
        definitions={s['slot_key']:s for s in self.template['_slots']}
        slots=[{**s, 'name':definitions[s['slot_key']].get('business_context',s['name']),
                'business_context':definitions[s['slot_key']].get('business_context',''),
                'text':definitions[s['slot_key']].get('template_text',''),
                'draft_saved':s['slot_key'] in plan.get('drafts',{})} for s in slots]
        next_cursor = None
        if offset + 50 < len(slots):
            next_cursor = "cursor_" + token_urlsafe(18)
            plan.setdefault("cursors", {})[next_cursor] = (section_key, offset + 50, writing_only)
        roles = {definition.get("scope_role", "school") for definition in self.template['_slots']
                 if definition["section_key"] == section_key}
        result.update({"slots": slots[offset:offset+50], "cursor": next_cursor,
                       "facts": [{"query_id": n["query_id"], "parameters": n["parameters"],
                                  "scope_roles": n["scope_roles"],
                                  "status": n["status"], "result_ref": n["result_ref"],
                                  "error_code": n["error_code"], "usage": "candidate_facts_require_period_validation"}
                                 for n in plan["nodes"]
                                 if "school" in roles or roles.intersection(n["scope_roles"])]})
        return result

    async def render(self, plan_ref, section_drafts):
        from .report_renderer import render
        if plan_ref != self.latest or plan_ref not in self.plans:
            raise DataError("PLAN_SUPERSEDED")
        plan = self.plans[plan_ref]
        if plan["status"] not in {"ready", "blocked"}:
            raise DataError("PLAN_NOT_READY")
        from .report_renderer import validate_drafts
        drafts = {**plan.get('drafts', {}), **validate_drafts(plan, section_drafts, self.services.current())}
        output=await self.services.call(render, self.template, plan, list(drafts.values()), self.services.current())
        plan['drafts']=drafts
        plan['rendered']=output
        plan.pop('validation',None)
        self._save(plan)
        return output

    def save_drafts(self, plan_ref, section_drafts):
        if plan_ref != self.latest:
            raise DataError('PLAN_SUPERSEDED')
        plan=self.plans[plan_ref]
        from .report_renderer import validate_drafts
        plan.setdefault('drafts', {}).update(validate_drafts(plan, section_drafts, self.services.current()))
        plan.pop('rendered',None)
        plan.pop('validation',None)
        self._save(plan)
        return {'saved':len(plan['drafts']), 'required':plan['coverage']['drafts_required']}

    async def close(self):
        for task in list(self.tasks):
            task.cancel()
        if self.tasks:
            await asyncio.gather(*list(self.tasks), return_exceptions=True)
