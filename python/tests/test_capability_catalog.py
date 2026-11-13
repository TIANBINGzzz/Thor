"""目录缓存命中省去校验，资产增删改和依赖变更必须即时失效。"""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from runtime import capabilities


class CapabilityCatalogTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / 'capabilities'
        self.skills = self.root / 'skills'
        for name, path in (('CAPABILITIES_ROOT', self.source), ('SKILLS_ROOT', self.skills)):
            path.mkdir()
            self.enterContext(patch.object(capabilities, name, path))
        self.catalog = capabilities.CapabilityCatalog()
        self.write('first')

    def write(self, ref, **extra):
        directory = self.source / ref
        directory.mkdir(exist_ok=True)
        (directory / 'CAPABILITY.md').write_text('业务规则', encoding='utf-8')
        path = directory / 'capability.json'
        path.write_text(json.dumps({'ref': ref, 'title': ref, 'description': '说明', **extra}), encoding='utf-8')
        return path

    def test_hits_skip_full_validation(self):
        with patch.object(capabilities, 'load_capabilities', wraps=capabilities.load_capabilities) as load:
            self.assertEqual(self.catalog['first'].name, 'first')
            self.assertEqual(list(self.catalog), ['first'])
            self.assertEqual(len(self.catalog), 1)
            self.assertEqual(len(self.catalog.values()), 1)
            self.assertEqual(load.call_count, 1)

    def test_existing_file_edit_with_unchanged_count_and_root_mtime_is_detected(self):
        self.assertEqual(self.catalog['first'].name, 'first')
        root_stat = self.source.stat()
        path = self.source / 'first/capability.json'
        old_stat = path.stat()
        path.write_text(path.read_text().replace('"title": "first"', '"title": "other"'), encoding='utf-8')
        os.utime(path, ns=(old_stat.st_atime_ns, old_stat.st_mtime_ns + 1_000_000_000))
        os.utime(self.source, ns=(root_stat.st_atime_ns, root_stat.st_mtime_ns))
        self.assertEqual(self.catalog['first'].name, 'other')
        path.write_text('{}', encoding='utf-8')
        with self.assertRaises(RuntimeError):
            self.catalog['first']

    def test_add_remove_do_not_serve_stale_catalog(self):
        self.assertEqual(len(self.catalog), 1)
        self.write('second')
        self.assertEqual(set(self.catalog), {'first', 'second'})
        (self.source / 'second/capability.json').unlink()
        self.assertEqual(set(self.catalog), {'first'})

    def test_skill_dependency_is_revalidated(self):
        skill = self.skills / 'review'
        skill.mkdir()
        (skill / 'skill.json').write_text(json.dumps({'ref': 'review', 'description': '核验'}), encoding='utf-8')
        (skill / 'SKILL.md').write_text('检查依据', encoding='utf-8')
        self.write('first', skillRefs=['review'])
        self.assertEqual(self.catalog['first'].skill_refs, ('review',))
        (skill / 'skill.json').write_text('{}', encoding='utf-8')
        with self.assertRaises(RuntimeError):
            self.catalog['first']

    def test_data_volume_capability_is_not_discovered(self):
        directory = self.root / '.scribe-runs/capabilities/managed-report'
        directory.mkdir(parents=True)
        (directory / 'CAPABILITY.md').write_text('业务规则', encoding='utf-8')
        (directory / 'capability.json').write_text(json.dumps({'ref': 'managed-report', 'title': '报告',
            'description': '说明', 'execution': {'mode': 'agent'}}), encoding='utf-8')
        # 即使旧数据目录仍存在，也不能进入当前能力目录。
        with patch.object(capabilities, 'MANAGED_CAPABILITIES_ROOT', directory.parent, create=True):
            self.assertEqual(set(self.catalog), {'first'})
