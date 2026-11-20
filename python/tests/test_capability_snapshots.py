"""验证 MySQL 本地审阅快照不会成为 Runtime 的运行来源。"""

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from runtime.configuration import execution_entry
from tests.deployment_fixtures import install_configuration_store


class CapabilitySnapshotTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch('runtime.config_store._STORE'))
        self.store = install_configuration_store()

    def test_exports_capability_and_skill_content_from_database(self):
        skill = self.store.get('skills', 'document-review')
        skill.update(content='DB skill body', resources={'references/checks.md': 'DB resource'})
        self.store.save('skills', 'document-review', skill)
        capability = self.store.get('capabilities', 'document-writing')
        capability['prompt'] = 'DB capability body'
        self.store.save('capabilities', 'document-writing', capability)

        from runtime.capability_snapshots import export_capability_snapshot
        with tempfile.TemporaryDirectory() as temporary:
            files = export_capability_snapshot('document-writing', output_root=temporary)
            root = Path(temporary) / 'document-writing'
            self.assertEqual((root / 'CAPABILITY.md').read_text(encoding='utf-8'),
                             'DB capability body')
            self.assertEqual((root / 'skills' / 'document-review' / 'SKILL.md').read_text(encoding='utf-8'),
                             'DB skill body')
            self.assertEqual((root / 'skills' / 'document-review' / 'references' / 'checks.md').read_text(encoding='utf-8'),
                             'DB resource')
            self.assertIn('skills/document-review/SKILL.md', files)

    def test_refresh_removes_only_obsolete_files_owned_by_previous_snapshot(self):
        from runtime.capability_snapshots import export_capability_snapshot
        skill = self.store.get('skills', 'document-review')
        skill['resources'] = {'old.md': 'old resource'}
        self.store.save('skills', 'document-review', skill)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / 'document-writing'
            export_capability_snapshot('document-writing', output_root=temporary)
            skill['resources'] = {'new.md': 'new resource'}
            self.store.save('skills', 'document-review', skill)
            export_capability_snapshot('document-writing', output_root=temporary)
            self.assertFalse((root / 'skills' / 'document-review' / 'old.md').exists())
            self.assertEqual((root / 'skills' / 'document-review' / 'new.md').read_text(encoding='utf-8'),
                             'new resource')

    def test_export_does_not_include_model_or_database_credentials(self):
        from runtime.capability_snapshots import export_capability_snapshot
        with tempfile.TemporaryDirectory() as temporary:
            export_capability_snapshot('document-writing', output_root=temporary)
            contents = '\n'.join(path.read_text(encoding='utf-8')
                                  for path in (Path(temporary) / 'document-writing').rglob('*')
                                  if path.is_file())
            self.assertNotIn('model-secret', contents)
            self.assertNotIn('private-db', contents)

    def test_snapshot_content_never_overrides_database_runtime_content(self):
        from runtime.capability_snapshots import export_capability_snapshot
        with tempfile.TemporaryDirectory() as temporary:
            export_capability_snapshot('document-writing', output_root=temporary)
            snapshot = Path(temporary) / 'document-writing' / 'skills' / 'document-review' / 'SKILL.md'
            snapshot.write_text('Edited local copy', encoding='utf-8')
            db_skill = self.store.get('skills', 'document-review')
            db_skill['content'] = 'Authoritative database content'
            self.store.save('skills', 'document-review', db_skill)
            current = execution_entry('document-writing')['capability']['_skills']['document-review']['_body']
            self.assertEqual(current, 'Authoritative database content')
            self.assertEqual(snapshot.read_text(encoding='utf-8'), 'Edited local copy')

    def test_untracked_local_file_is_never_overwritten(self):
        from runtime.capability_snapshots import export_capability_snapshot
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / 'document-writing'
            root.mkdir(parents=True)
            local = root / 'CAPABILITY.md'
            local.write_text('local edit', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'snapshot_file_not_owned'):
                export_capability_snapshot('document-writing', output_root=temporary)
            self.assertEqual(local.read_text(encoding='utf-8'), 'local edit')

    def test_database_resource_cannot_escape_skill_directory(self):
        from runtime.capability_snapshots import export_capability_snapshot
        skill = self.store.get('skills', 'document-review')
        skill['resources'] = {'../outside.md': 'outside'}
        self.store.save('skills', 'document-review', skill)
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(ValueError, 'snapshot_path_invalid'):
                export_capability_snapshot('document-writing', output_root=temporary)
            self.assertFalse((Path(temporary) / 'outside.md').exists())

    def test_database_resource_must_be_text(self):
        from runtime.capability_snapshots import export_capability_snapshot
        skill = self.store.get('skills', 'document-review')
        skill['resources'] = {'checks.json': {'invalid': True}}
        self.store.save('skills', 'document-review', skill)
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(ValueError, 'snapshot_content_invalid'):
                export_capability_snapshot('document-writing', output_root=temporary)
