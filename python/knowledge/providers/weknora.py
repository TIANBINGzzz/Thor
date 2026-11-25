"""WeKnora v0.9.1 的只读检索和单分块读取适配器。"""

from urllib.parse import quote

import httpx


class WeKnoraProvider:
    def validate(self, connection_config, library_config):
        if connection_config['provider'] != 'weknora':
            raise ValueError('knowledge_provider_unsupported')
        if (not isinstance(connection_config['config'], dict)
                or set(connection_config['config']) != {'workspace_id'}
                or not str(connection_config['config']['workspace_id'])):
            raise ValueError('knowledge_workspace_invalid')
        credentials = connection_config['credentials']
        if not isinstance(credentials, dict) or not isinstance(credentials.get('api_key'), str) or not credentials['api_key']:
            raise ValueError('knowledge_key_required')
        if library_config is None:
            return
        config = library_config['config']
        if not isinstance(config, dict) or set(config) - {'tag_ids'}:
            raise ValueError('knowledge_library_config_invalid')
        if 'tag_ids' in config and (not isinstance(config['tag_ids'], list)
                or any(not isinstance(tag, str) or not tag for tag in config['tag_ids'])):
            raise ValueError('knowledge_tag_ids_invalid')

    async def _request(self, connection, method, path, *, client_factory, **kwargs):
        headers = {
            'Authorization': 'Bearer ' + connection['credentials']['api_key'],
            'X-Tenant-ID': str(connection['config']['workspace_id']),
        }
        async with client_factory(timeout=connection['timeoutSeconds']) as client:
            response = await client.request(method, connection['baseUrl'].rstrip('/') + '/api/v1' + path,
                                            headers=headers, **kwargs)
        response.raise_for_status()
        return response.json()

    async def search(self, connection, library, query, limit, *, client_factory=httpx.AsyncClient):
        body = {'query_text': query, 'match_count': limit}
        if 'tag_ids' in library['config']:
            body['tag_ids'] = library['config']['tag_ids']
        response = await self._request(
            connection, 'POST', '/knowledge-bases/' + quote(library['externalId'], safe='') + '/hybrid-search',
            client_factory=client_factory, json=body,
        )
        return [{
            'chunkId': item['id'],
            'documentId': item['knowledge_id'],
            'chunkIndex': item['chunk_index'],
            'documentTitle': item['knowledge_title'] or item['knowledge_filename'],
            'content': item['content'],
            'score': item['score'],
            'locations': [_location(locator) for locator in item['source_locators']],
        } for item in response['data']]

    async def read(self, connection, chunk_id, *, client_factory=httpx.AsyncClient):
        response = await self._request(connection, 'GET', '/chunks/by-id/' + quote(chunk_id, safe=''),
                                        client_factory=client_factory)
        return response['data']['content']


def _location(locator):
    location = {key: locator[key] for key in ('type', 'quote')}
    if 'partial' in locator:
        location['partial'] = locator['partial']
    for source, target in (
        ('page', 'page'), ('bbox', 'bbox'), ('block', 'block'), ('slide', 'slide'),
        ('title', 'title'), ('sheet', 'sheet'), ('row_start', 'rowStart'), ('row_end', 'rowEnd'),
        ('start', 'start'), ('end', 'end'), ('start_ms', 'startMs'), ('end_ms', 'endMs'),
        ('section', 'section'),
    ):
        if source in locator:
            location[target] = locator[source]
    return location
