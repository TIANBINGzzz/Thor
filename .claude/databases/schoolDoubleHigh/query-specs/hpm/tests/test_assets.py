"""验证查询资产之间的引用、参数和输出契约，不作为 SQL 安全执行器。"""
from pathlib import Path
import json
import re
import unittest

BASE = Path(__file__).resolve().parents[1]
ROOT = BASE.parents[4]


class AssetContractTests(unittest.TestCase):
    def setUp(self):
        self.specs = {p.stem: json.loads(p.read_text(encoding='utf-8')) for p in (BASE/'specs').glob('*.json')}
        self.source = json.loads((BASE.parents[1]/'source.json').read_text(encoding='utf-8'))
        self.tables = json.loads((BASE/'coverage.json').read_text(encoding='utf-8'))['tables']

    def test_sql_parameters_outputs_tables_and_source_registration(self):
        files = set()
        for id, spec in self.specs.items():
            with self.subTest(query=id):
                self.assertEqual(spec['id'],id)
                self.assertTrue(spec['name'] and spec['description'] and spec['grain'])
                self.assertNotIn('source_keys', spec)
                self.assertEqual(self.source['source_key'], 'schoolDoubleHigh')
                self.assertEqual(len(spec['output']),len({f['name'] for f in spec['output']}))
                for f in spec['output']:
                    self.assertTrue(f['description'])
                    if f['name'].endswith('_id'): self.assertEqual(f['visibility'],'internal_only')
                if spec['sql_file']:
                    path = BASE/spec['sql_file']
                    self.assertTrue(path.resolve().is_relative_to(BASE.resolve()))
                    files.add(path.name)
                    sql=path.read_text(encoding='utf-8')
                    self.assertEqual(set(re.findall(r':([a-z_]+)',sql)),set(spec['parameters']))
                    self.assertEqual(set(re.findall(r'\bt_hpm_[a-z_]+',sql)),set(spec['tables']))
                    if spec['status'] == 'defined':
                        self.assertTrue(set(spec['tables']) <= set(self.tables))
                    self.assertRegex(sql.strip(),r'^(SELECT|WITH)\b')
                    self.assertNotIn(';',sql)  # 一条无尾分号的语句，便于驱动和核验器装配。
                    self.assertNotRegex(sql,r'(?i)SELECT\s+\*|\b(?:INSERT|UPDATE|DELETE|DROP|TRUNCATE|GRANT|OUTFILE|LOAD_FILE|SLEEP)\b')
                else:
                    self.assertEqual(spec['status'],'needs_definition')
                    self.assertTrue(spec['blockers'])
                for dependency in spec.get('requires_queries',[]) + spec.get('candidate_queries',[]):
                    self.assertIn(dependency,self.specs)
                for evidence in spec['evidence']:
                    self.assertTrue((ROOT/evidence).is_file(),evidence)
        self.assertEqual(files,{p.name for p in (BASE/'sql').glob('*.sql')})

    def test_catalog_and_18_question_coverage(self):
        catalog=json.loads((BASE/'catalog.json').read_text(encoding='utf-8'))
        self.assertEqual({q['id'] for q in catalog['queries']},set(self.specs))
        coverage=json.loads((BASE/'coverage.json').read_text(encoding='utf-8'))
        self.assertEqual(set(coverage['questions']),{f'Q{i}' for i in range(1,19)})
        for mapping in coverage['questions'].values():
            spec=self.specs[mapping['query_id']]
            self.assertEqual(spec['status'],'defined')
            self.assertTrue(set(mapping['bindings']) <= set(spec['parameters']))
        self.assertEqual(set(coverage['tables']),set(self.tables))
        self.assertTrue(all(coverage['tables'].values()))

    def test_template_rules_and_all_40_tables_keep_report_source(self):
        path=ROOT/'.claude/workflows/writing-docx/templates/szpt-midterm/query-bindings.json'
        bindings=json.loads(path.read_text(encoding='utf-8'))
        self.assertEqual(bindings['source_key'],'schoolDoubleHigh')
        self.assertEqual({t['table_id'] for t in bindings['tables']},{f'T{i:02}' for i in range(1,41)})
        self.assertEqual(len(bindings['tables']),40)
        for mapping in bindings['rules'].values():
            for id in mapping['query_ids']:
                self.assertIn(id,self.specs)
        for table in bindings['tables']:
            self.assertEqual(table['source_key'],'schoolDoubleHigh')
            self.assertTrue(set(table['rules']) <= set(bindings['rules']))
        source=(path.parent/bindings['source_document']).read_text(encoding='utf-8')
        rule_section=source.split('## 取数规则索引',1)[1].split('###',1)[0]
        self.assertEqual(set(re.findall(r'^\| ([A-Z]) \|',rule_section,re.M)),set(bindings['rules']))


if __name__ == '__main__':
    unittest.main()
