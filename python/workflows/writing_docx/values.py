"""Resolve explicit text bindings and evidence-backed absence without guessing."""
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
    if binding.get('intentional_blank') and not binding['required']:
        return {'value_status': 'filled', 'value': ''}
    refs = []
    for key in binding.get('evidence_datasets', []):
        refs.append(dataset_record(key, plan, executor)['result_ref'])
    if binding['kind'] == 'narrative':
        return {'value_status':'awaiting_draft', 'evidence_refs':refs}
    resolution = binding.get('resolution')
    if resolution:
        for key in resolution.get('require_empty', []):
            if dataset_record(key, plan, executor)['rows']:
                raise DataError('ABSENCE_NOT_CONFIRMED')
        return {'value_status':'unavailable', 'value':resolution['text'],
                'reason':resolution['reason'], 'evidence_refs':refs}
    if 'text_template' not in binding:
        return {'value_status': 'definition_missing'}
    values = {}
    for name, definition in binding.get('values', {}).items():
        if 'report_parameter' in definition:
            value = plan['report_parameters'][definition['report_parameter']]
            if isinstance(value, list): value = '、'.join(value)
        else:
            record = dataset_record(definition['dataset_key'], plan, executor)
            rows = [r for r in record['rows'] if all(r.get(k)==v for k,v in definition.get('selector', {}).items())]
            if len(rows) != 1:
                raise DataError('BINDING_VALUE_AMBIGUOUS')
            column = next((c for c in record['output'] if c['name']==definition['field']), {})
            if not column or column.get('visibility')=='internal_only':
                raise DataError('BINDING_INVALID')
            value = rows[0][definition['field']]
            refs.append(record['result_ref'])
            if value is None:
                value = definition.get('null_text', '未填报')
        values[name] = str(value)
    return {'value_status':'filled','value':Template(binding['text_template']).substitute(values),
            'evidence_refs':list(dict.fromkeys(refs))}
