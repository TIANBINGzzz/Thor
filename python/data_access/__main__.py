"""Operator CLI for registered sources, asset validation and connection probes."""

import argparse
import json
import os

from .catalog import Catalog, PROJECT_ROOT
from .connections import Connections, load_config
from .context import DataError
from .sql_policy import validate_sql


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['list', 'validate', 'probe'])
    parser.add_argument('--config', default=os.environ.get('CCSDK_DATA_CONFIG'))
    parser.add_argument('--source')
    args = parser.parse_args()
    catalog = Catalog()
    try:
        sources = [catalog.source(args.source)] if args.source else catalog.sources()
        if args.command == 'list':
            print(json.dumps([{'source_key': s['source_key'], 'name': s['name'], 'domains': list(s['profiles'])}
                              for s in sources], ensure_ascii=False))
            return
        config, base = load_config(args.config, PROJECT_ROOT)
        result = []
        for source in sources:
            policy = config['policies'][source['policy_ref']]
            connection = config['connections'][source['connection_ref']]
            if any(v.get('source_key') != source['source_key'] or not v.get('revision') for v in [policy, connection]):
                raise DataError('CONFIG_INVALID')
            count = 0
            for domain in source['profiles']:
                _, index = catalog.domain(source['source_key'], domain)
                for entry in index['queries']:
                    spec = catalog.spec(source['source_key'], domain, entry['id'])
                    if spec['status'] == 'defined':
                        validate_sql(catalog.sql(source['source_key'], domain, spec), policy['domains'][domain])
                        count += 1
            if args.command == 'probe':
                with Connections(dict(os.environ), base).snapshot(connection) as db:
                    db.exec_driver_sql('SELECT 1').fetchone()
            result.append({'source_key': source['source_key'], 'defined_queries_validated': count,
                           'connection_probed': args.command == 'probe',
                           'authorization_configured': bool(policy.get('users')) and bool(policy.get('business_tenant_id'))
                           and (policy.get('project_scope', {}).get('mode') == 'all_school'
                                or bool(policy.get('project_scope', {}).get('project_ids')))})
        print(json.dumps(result, ensure_ascii=False))
    except Exception as error:
        print(json.dumps({'status':'failed','code': error.code if isinstance(error, DataError) else 'CONFIG_OR_CONNECTION_INVALID'}))
        raise SystemExit(1) from None


if __name__ == '__main__':
    main()
