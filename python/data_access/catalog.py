"""Read only registered model-facing assets within their package boundary."""

import json
import re
from copy import deepcopy
from pathlib import Path

from .context import DataError, fingerprint

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATABASES_ROOT = PROJECT_ROOT / ".claude/databases"
KEY = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,95}$")


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


class Catalog:
    def __init__(self, root=DATABASES_ROOT):
        self.root = Path(root).resolve()
        self._contents = None

    def freeze(self, source_keys):
        frozen = Catalog(self.root)
        frozen._contents = {}
        for source_key in source_keys:
            self.source(source_key)
            for path in (self.root / source_key).rglob('*'):
                if path.is_file() and path.suffix in {'.json', '.md', '.sql'} and 'tests' not in path.parts:
                    resolved = asset_path(self.root, str(path.relative_to(self.root)))
                    frozen._contents[resolved] = resolved.read_text(encoding='utf-8')
        return frozen

    def _text(self, path):
        if self._contents is not None:
            if path not in self._contents:
                raise DataError('ASSET_MISMATCH')
            return self._contents[path]
        return path.read_text(encoding='utf-8')

    def _json(self, path):
        return json.loads(self._text(path))

    def source(self, source_key):
        path = asset_path(self.root, f"{key(source_key)}/source.json")
        data = self._json(path)
        if data.get("source_key") != source_key or data.get("enabled") is not True:
            raise DataError("SOURCE_UNAVAILABLE")
        return data

    def sources(self):
        return [self.source(p.parent.name) for p in sorted(self.root.glob("*/source.json"))
                if read_json(p).get("enabled") is True]

    def domain(self, source_key, domain):
        source = self.source(source_key)
        profile = source.get("profiles", {}).get(key(domain))
        if not profile:
            raise DataError("DOMAIN_UNAVAILABLE")
        path = asset_path(self.root / source_key, f"{profile}/catalog.json")
        return path.parent, self._json(path)

    def spec(self, source_key, domain, query_id):
        root, catalog = self.domain(source_key, domain)
        entry = next((q for q in catalog["queries"] if q["id"] == key(query_id)), None)
        if not entry:
            raise DataError("QUERY_UNAVAILABLE")
        spec = self._json(asset_path(root, entry["spec_file"]))
        if spec.get("id") != query_id or spec.get("status") != entry["status"]:
            raise DataError("ASSET_MISMATCH")
        return spec

    def sql(self, source_key, domain, spec):
        root, _ = self.domain(source_key, domain)
        return self._text(asset_path(root, spec["sql_file"]))

    def documents(self, source_key, domain, document_keys=None):
        root, catalog = self.domain(source_key, domain)
        registered = catalog.get("documents", {})
        chosen = document_keys if document_keys is not None else []
        result = {}
        for name in chosen:
            if name not in registered:
                raise DataError("DOCUMENT_UNAVAILABLE")
            path = asset_path(root, registered[name])
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
        root = self.root / key(source_key)
        self.source(source_key)
        return fingerprint([(str(p.relative_to(root)), fingerprint(self._text(p.resolve())))
                            for p in sorted(root.rglob("*"))
                            if p.is_file() and p.suffix in {".json", ".md", ".sql"} and 'tests' not in p.parts])
