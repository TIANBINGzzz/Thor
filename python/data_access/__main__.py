"""Operator CLI for registered sources, asset validation and connection probes."""

import argparse
import json
import os

from .catalog import Catalog
from .connections import Connections, load_config
from .context import DataError
from .sql_policy import validate_sql


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['list', 'validate', 'check-config', 'probe'])
    parser.add_argument('--source')
    args = parser.parse_args()
    catalog = Catalog()
    try:
        if args.command == 'check-config':
            # 构建机仅核验运行时可加载的 JSON 结构，不连接部署环境的内网数据库。
            config = load_config(os.environ)
            if not config:
                raise DataError('CONFIG_INVALID')
            print(json.dumps({'status': 'ok', 'sources_checked': len(config)}))
            return
        sources = [catalog.source(args.source)] if args.source else catalog.sources()
        if args.command == 'list':
            print(json.dumps([{'source_key': s['source_key'], 'name': s['name'], 'domains': list(s['domains'])}
                              for s in sources], ensure_ascii=False))
            return
        result = []
        for source in sources:
            count = 0
            for domain in source['domains']:
                _, index = catalog.domain(source['source_key'], domain)
                for entry in index['queries']:
                    spec = catalog.spec(source['source_key'], domain, entry['id'])
                    if spec['status'] == 'defined':
                        validate_sql(catalog.sql(source['source_key'], domain, spec), catalog.schema(source['source_key'], domain))
                        count += 1
            if args.command == 'probe':
                config = load_config(os.environ).get(source['source_key'])
                if config is None:
                    raise DataError('CONNECTION_UNAVAILABLE')
                connection = config['connection']
                if connection.get('source_key') != source['source_key'] or not connection.get('revision'):
                    raise DataError('CONFIG_INVALID')
                with Connections().snapshot(connection) as db:
                    db.exec_driver_sql('SELECT 1').fetchone()
            result.append({'source_key': source['source_key'], 'defined_queries_validated': count,
                           'connection_probed': args.command == 'probe'})
        print(json.dumps(result, ensure_ascii=False))
    except Exception as error:
        print(json.dumps({'status':'failed','code': error.code if isinstance(error, DataError) else 'CONFIG_OR_CONNECTION_INVALID'}))
        raise SystemExit(1) from None


if __name__ == '__main__':
    main()
