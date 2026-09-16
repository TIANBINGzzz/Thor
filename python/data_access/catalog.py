"""Index business queries from grouped YAML assets frozen for each Run."""

import json
import re
import unicodedata
from copy import deepcopy
from pathlib import Path

import yaml

from .context import DataError, fingerprint

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATABASES_ROOT = PROJECT_ROOT / ".claude/databases"
KEY = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,95}$")


class UniqueLoader(yaml.SafeLoader):
    pass


def unique_mapping(loader, node, deep=False):
    result = {}
    for key_node, value_node in node.value:
        name = loader.construct_object(key_node, deep=deep)
        if not isinstance(name, str) or name in result:
            raise DataError('ASSET_MISMATCH')
        result[name] = loader.construct_object(value_node, deep=deep)
    return result


UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, unique_mapping)


def key(value):
    if not isinstance(value, str) or not KEY.fullmatch(value):
        raise DataError("INVALID_REFERENCE")
    return value


def asset_path(root: Path, relative: str) -> Path:
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
        raise DataError("ASSET_PATH_INVALID")
    root = root.resolve()
    path = (root / relative).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise DataError("ASSET_PATH_INVALID")
    return path


def read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise DataError("CONFIG_INVALID") from None


def search_score(spec, intent):
    """Rank explicit business aliases first, then overlapping Chinese word pairs."""
    def normalize(value):
        return re.sub(r"[\W_]+", "", unicodedata.normalize("NFKC", value).casefold())

    query = normalize(intent)
    if not query:
        return 0
    labels = [spec["id"], spec["name"], *spec.get("aliases", [])]
    direct = max(((10000 if label == query else 0) + 100 * min(len(label), len(query))
                  for label in map(normalize, labels)
                  if label and (label in query or query in label)), default=0)
    text = normalize(" ".join([*labels, spec.get("description", "")]))
    pairs = {part[i:i+2] for part in re.findall(r"[\u4e00-\u9fff]+", query) for i in range(len(part)-1)}
    overlap = sum(pair in text for pair in pairs)
    return direct + overlap if direct or overlap >= 2 else 0


class Catalog:
    def __init__(self, root=DATABASES_ROOT):
        self.root = Path(root).resolve()
        self._contents = None
        self._domains = {}

    def freeze(self, source_keys):
        frozen = Catalog(self.root)
        frozen._contents = {}
        for source_key in source_keys:
            source = self.source(source_key)
            root = self.root / source_key
            paths = [self._path(root, "source.json")]
            for domain in source["domains"]:
                base, config, specs = self._domain(source_key, domain)
                paths += self._metric_files(base)
                paths += [self._path(root, config['schema'])]
                paths += [self._path(root, path) for path in config.get("documents", {}).values()]
            for path in paths:
                frozen._contents[path] = self._text(path)
        return frozen

    def _path(self, root, relative):
        if self._contents is None:
            return asset_path(root, relative)
        if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
            raise DataError("ASSET_PATH_INVALID")
        path = (root / relative).resolve()
        if not path.is_relative_to(root.resolve()) or path not in self._contents:
            raise DataError("ASSET_PATH_INVALID")
        return path

    def _text(self, path):
        return self._contents[path] if self._contents is not None else path.read_text(encoding="utf-8")

    def _json(self, path):
        try:
            return json.loads(self._text(path))
        except (OSError, ValueError):
            raise DataError("CONFIG_INVALID") from None

    def source(self, source_key):
        path = self._path(self.root, f"{key(source_key)}/source.json")
        data = self._json(path)
        if data.get("source_key") != source_key or data.get("enabled") is not True:
            raise DataError("SOURCE_UNAVAILABLE")
        return data

    def sources(self):
        return [self.source(p.parent.name) for p in sorted(self.root.glob("*/source.json"))
                if read_json(p).get("enabled") is True]

    def sources_for(self, capability_ref):
        return [s['source_key'] for s in self.sources() if capability_ref in s.get('capabilities', [])]

    def schema(self, source_key, domain):
        definition = self.source(source_key).get('domains', {}).get(key(domain))
        if not definition:
            raise DataError('DOMAIN_UNAVAILABLE')
        return self._json(self._path(self.root / source_key, definition['schema']))

    def _domain(self, source_key, domain):
        cache_key = (key(source_key), key(domain))
        if cache_key in self._domains:
            return self._domains[cache_key]
        config = self.source(source_key).get("domains", {}).get(domain)
        if not config:
            raise DataError("DOMAIN_UNAVAILABLE")
        source_root = (self.root / source_key).resolve()
        relative = config['metrics']
        root = (source_root / relative).resolve()
        if Path(relative).is_absolute() or not root.is_relative_to(source_root):
            raise DataError('ASSET_PATH_INVALID')
        specs = {}
        for path in self._metric_files(root):
            try:
                bundle = yaml.load(self._text(self._path(root, path.name)), Loader=UniqueLoader)
            except (OSError, yaml.YAMLError):
                raise DataError('ASSET_MISMATCH') from None
            if not isinstance(bundle, dict) or set(bundle) - {'parameters', 'metrics', 'pending'}:
                raise DataError('ASSET_MISMATCH')
            shared, metrics, pending = bundle.get('parameters', {}), bundle.get('metrics', []), bundle.get('pending', {})
            if not isinstance(shared, dict) or not isinstance(metrics, list) or not isinstance(pending, dict):
                raise DataError('ASSET_MISMATCH')
            for metric in metrics:
                required = {'id', 'name', 'description', 'parameters', 'grain', 'sql', 'output', 'validation'}
                if not isinstance(metric, dict) or set(metric) != required:
                    raise DataError('ASSET_MISMATCH')
                query_id = key(metric['id'])
                if query_id in specs or not isinstance(metric['sql'], str) or not metric['sql'].strip():
                    raise DataError('ASSET_MISMATCH')
                names = metric['parameters']
                if (not isinstance(names, list) or any(not isinstance(n, str) for n in names)
                        or len(names) != len(set(names)) or any(n not in shared for n in names)
                        or 'tenant_id' in names or not isinstance(metric['validation'], dict)
                        or not isinstance(metric['output'], list)):
                    raise DataError('ASSET_MISMATCH')
                parameters = {n: deepcopy(shared[n]) for n in names}
                if re.search(r':tenant_id\b', metric['sql']):
                    parameters['tenant_id'] = {'type': 'string', 'required': True, 'origin': 'authorized_context'}
                if set(re.findall(r':([a-z_]+)', metric['sql'])) != set(parameters):
                    raise DataError('ASSET_MISMATCH')
                validation = metric['validation']
                required_values = validation.get('required_values', [])
                if not isinstance(required_values, list) or any(not isinstance(n, str) or n not in names for n in required_values):
                    raise DataError('ASSET_MISMATCH')
                for name in required_values:
                    definition = parameters[name]
                    definition['required'] = True
                    if isinstance(definition.get('type'), list):
                        definition['type'] = [t for t in definition['type'] if t != 'null']
                specs[query_id] = {**metric, 'parameters': parameters, 'status': 'defined',
                    'version': fingerprint(metric), 'aliases': validation.get('aliases', []),
                    'semantics': validation.get('rules', []), 'requires_queries': validation.get('requires_queries', []),
                    'checks': validation.get('checks', []), 'candidate_queries': validation.get('candidate_queries', [])}
            for query_id, spec in pending.items():
                if (key(query_id) in specs or not isinstance(spec, dict) or spec.get('status') not in {'blocked', 'needs_definition'}
                        or not spec.get('blockers')):
                    raise DataError('ASSET_MISMATCH')
                specs[query_id] = {**spec, 'id': query_id, 'parameters': {}, 'output': [], 'sql': None}
        result = (root, config, specs)
        if self._contents is not None:
            self._domains[cache_key] = result
        return result

    def _metric_files(self, root):
        paths = [p for p in self._contents if p.parent == root and p.suffix == '.yaml'] \
            if self._contents is not None else list(root.glob('*.yaml'))
        if not paths:
            raise DataError('ASSET_MISMATCH')
        return sorted(paths)

    def domain(self, source_key, domain):
        root, config, specs = self._domain(source_key, domain)
        queries = [{k: spec[k] for k in ("id", "name", "description", "status")}
                   for _, spec in sorted(specs.items())]
        public = {k:deepcopy(config.get(k, {})) for k in ('entities','documents')}
        public['documents'] = {'schema': config['schema'], **public['documents']}
        return root, {**public, "queries": queries}

    def spec(self, source_key, domain, query_id):
        spec = self._domain(source_key, domain)[2].get(key(query_id))
        if spec is None:
            raise DataError("QUERY_UNAVAILABLE")
        return deepcopy(spec)

    def sql(self, source_key, domain, spec):
        return self.spec(source_key, domain, spec['id'])['sql']

    def documents(self, source_key, domain, document_keys=None):
        _, config, _ = self._domain(source_key, domain)
        root = self.root / source_key
        registered = config.get("documents", {})
        result = {}
        for name in document_keys or []:
            if name == 'schema':
                schema = self.schema(source_key, domain)
                content = '\n\n'.join(f'## {table}\n{description}'
                    for table,description in schema.get('descriptions', {}).items())
            else:
                if name not in registered:
                    raise DataError("DOCUMENT_UNAVAILABLE")
                path = self._path(root, registered[name])
                if path.suffix != ".md" or "not_for_model" in str(path).lower():
                    raise DataError("DOCUMENT_UNAVAILABLE")
                content = self._text(path)
            if len(content.encode()) > 24_000:
                raise DataError("DOCUMENT_TOO_LARGE")
            result[name] = content
        if sum(len(s.encode()) for s in result.values()) > 80_000:
            raise DataError("DOCUMENT_TOO_LARGE")
        return result

    def revision(self, source_key):
        if self._contents is None:
            return self.freeze([source_key]).revision(source_key)
        root = self.root / key(source_key)
        self.source(source_key)
        return fingerprint([(p.relative_to(root).as_posix(), fingerprint(content))
                            for p, content in sorted(self._contents.items()) if p.is_relative_to(root)])
