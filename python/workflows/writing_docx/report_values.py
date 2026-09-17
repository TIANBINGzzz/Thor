"""Resolve deterministic values; all other editable locations require a draft."""
from string import Template

from data_access.context import DataError


def dataset_record(key, plan, executor):
    nodes = [n for n in plan['nodes'] if key in n['dataset_keys']]
    if len(nodes) != 1 or nodes[0]['status'] != 'succeeded':
        raise DataError('BINDING_DATA_UNAVAILABLE')
    return executor.results.get(nodes[0]['result_ref'])


def resolve_value(binding, plan, executor):
    if binding['kind'] == 'static':
        return {'value_status': 'static'}
    refs = []
    gaps = []
    for key in binding.get('evidence_datasets', []):
        try:
            refs.append(dataset_record(key, plan, executor)['result_ref'])
        except DataError as error:
            if error.code != 'BINDING_DATA_UNAVAILABLE':
                raise
            gaps.append(key)
    if 'text_template' not in binding:
        return {'value_status':'awaiting_draft', 'evidence_refs':list(dict.fromkeys(refs)), 'draftable':True,
                'unavailable_datasets':gaps}
    values = {}
    missing_values = []
    for name, definition in binding.get('values', {}).items():
        if 'report_parameter' in definition:
            value = plan['report_parameters'].get(definition['report_parameter'])
            if isinstance(value, list): value = '、'.join(value)
        else:
            try:
                record = dataset_record(definition['dataset_key'], plan, executor)
            except DataError as error:
                if error.code != 'BINDING_DATA_UNAVAILABLE':
                    raise
                missing_values.append(name)
                continue
            rows = [r for r in record['rows'] if all(r.get(k)==v for k,v in definition.get('selector', {}).items())]
            if len(rows) > 1:
                raise DataError('BINDING_VALUE_AMBIGUOUS')
            column = next((c for c in record['output'] if c['name']==definition['field']), {})
            if not column or column.get('visibility')=='internal_only':
                raise DataError('BINDING_INVALID')
            value = rows[0][definition['field']] if rows else None
            refs.append(record['result_ref'])
        if value is None or not str(value).strip():
            missing_values.append(name)
            continue
        values[name] = str(value)
    if missing_values:
        return {'value_status':'awaiting_draft', 'draftable':True,
                'evidence_refs':list(dict.fromkeys(refs)), 'unavailable_datasets':gaps,
                'missing_values':missing_values}
    return {'value_status':'filled','value':Template(binding['text_template']).substitute(values),
            'evidence_refs':list(dict.fromkeys(refs))}
