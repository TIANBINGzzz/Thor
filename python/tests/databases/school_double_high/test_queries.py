"""在内存 SQLite 上验证查询口径；MySQL 字段投影核验单独记录，二者不等同。"""
from pathlib import Path
import json
import sqlite3
import sys
import unittest

ROOT = Path(__file__).resolve().parents[4]
BASE = ROOT / '.claude/databases/schoolDoubleHigh/metrics/hpm'
sys.path.insert(0, str(ROOT/'python'))
from data_access.catalog import Catalog
COMMON = 'tenant_id_ TEXT, delete_flag_ TEXT'
TABLES = {
    'project': 'id_ TEXT, name_ TEXT, high_flag_ TEXT, start_time_ TEXT, end_time_ TEXT, level_name_ TEXT, progress_ REAL',
    'stage': 'id_ TEXT, project_id_ TEXT, name_ TEXT, start_time_ TEXT, end_time_ TEXT, current_flag_ TEXT',
    'module': 'project_id_ TEXT, performance_stage_flag_ TEXT',
    'task': 'id_ TEXT, project_id_ TEXT, stage_id_ TEXT, parent_id_ TEXT, name_ TEXT, code_ TEXT, level_ INTEGER, high_flag_ TEXT, progress_ REAL, target_value_ TEXT, complete_value_ TEXT, state_ TEXT',
    'task_feedback': 'id_ TEXT, project_id_ TEXT, task_id_ TEXT, state_ TEXT, attachment_ TEXT, date_ TEXT, create_time_ TEXT, content_ TEXT, progress_ REAL, complete_progress_ REAL',
    'task_org': 'project_id_ TEXT, task_id_ TEXT, main_org_id_ TEXT, main_org_name_ TEXT',
    'task_member': 'project_id_ TEXT, task_id_ TEXT, user_id_ TEXT, user_name_ TEXT, type_ TEXT',
    'member': 'project_id_ TEXT, user_id_ TEXT, user_name_ TEXT, type_ TEXT',
    'fund': 'id_ TEXT, project_id_ TEXT, stage_id_ TEXT, task_id_ TEXT, level_ INTEGER, ' + ', '.join(
        f'{kind}_{source}_money_ REAL' for kind in ('budget', 'investment', 'execute', 'arrival')
        for source in ('total', 'centre', 'province', 'place', 'organizer', 'enterprise', 'alone')),
    'performance': 'id_ TEXT, project_id_ TEXT, stage_id_ TEXT, parent_id_ TEXT, first_item_id_ TEXT, second_item_id_ TEXT, name_ TEXT, code_ TEXT, level_ INTEGER, high_flag_ TEXT, progress_ REAL, target_value_ TEXT, finish_value_ TEXT',
    'task_performance_relation': 'project_id_ TEXT, task_id_ TEXT, performance_id_ TEXT',
    'performance_feedback': 'id_ TEXT, project_id_ TEXT, performance_id_ TEXT, create_time_ TEXT, year_target_value_ TEXT, total_target_value_ TEXT, year_complete_value_ TEXT, total_complete_value_ TEXT, progress_ REAL, total_progress_ REAL, state_ TEXT, content_ TEXT, attachment_ TEXT',
    'performance_org': 'project_id_ TEXT, performance_id_ TEXT, main_org_id_ TEXT, main_org_name_ TEXT',
}


class QuerySemanticsTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        self.db.row_factory = sqlite3.Row
        for name, columns in TABLES.items():
            # 两类部门关系表在真实数据库中没有 delete_flag_，测试也不提供它。
            shared = 'tenant_id_ TEXT' if name.endswith(('_org','_relation')) else COMMON
            self.db.execute(f'CREATE TABLE t_hpm_project{("_" + name) if name != "project" else ""} ({shared}, {columns})')
        catalog=Catalog().freeze(['schoolDoubleHigh'])
        self.specs = {q['id']:catalog.spec('schoolDoubleHigh','hpm',q['id'])
                      for q in catalog.domain('schoolDoubleHigh','hpm')[1]['queries']}

    def tearDown(self):
        self.db.close()

    def add(self, table, **values):
        values = {'tenant_id_': 'tenant-a', **({} if table.endswith(('_org','_relation')) else {'delete_flag_': '0'}), **values}
        physical = 't_hpm_project' + ('_' + table if table != 'project' else '')
        self.db.execute(f'INSERT INTO {physical} ({",".join(values)}) VALUES ({",".join("?" for _ in values)})', list(values.values()))

    def query(self, id, **params):
        spec = self.specs[id]
        values = {p: None for p in spec['parameters']}
        values.update({p:v for p,v in {'tenant_id':'tenant-a', 'threshold':50}.items() if p in values})
        values.update(params)
        result = self.db.execute(spec['sql'], values)
        self.assertEqual([d[0] for d in result.description], [f['name'] for f in spec['output']])
        return [dict(row) for row in result.fetchall()]

    def project(self, id='p1', **kw):
        self.add('project', id_=id, name_='项目-'+id, high_flag_='1', **kw)

    def task(self, id, **kw):
        self.add('task', **{'id_':id,'project_id_':'p1','stage_id_':'s1','level_':3,'high_flag_':'1','name_':'任务-'+id, **kw})

    def fund(self, id, **kw):
        self.add('fund', **{'id_':id,'project_id_':'p1','stage_id_':'s1','level_':1, **kw})

    def perf(self, id, **kw):
        self.add('performance', **{'id_':id,'project_id_':'p1','stage_id_':'s1','level_':3,'name_':'指标-'+id, **kw})

    def test_all_defined_sql_prepares_and_empty_is_not_zero_progress(self):
        for id, spec in self.specs.items():
            if spec['status'] == 'defined':
                with self.subTest(query=id): self.query(id)
        progress = self.query('task_progress_summary', level=3)[0]
        self.assertEqual(progress['task_count'], 0)
        self.assertIsNone(progress['avg_progress'])
        self.assertIsNone(progress['completion_rate'])
        money = self.query('fund_totals')[0]
        self.assertIsNone(money['budget_amount'])
        self.assertIsNone(money['budget_execution_rate'])

    def test_project_resolution_includes_city_projects_without_crossing_scope(self):
        self.project()
        self.add('project', id_='city', name_='市级专业群', high_flag_='0', level_name_='市级')
        self.add('project', id_='foreign', name_='其他学校', tenant_id_='tenant-b', high_flag_='1')
        self.add('project', id_='deleted', name_='已删除', delete_flag_='1', high_flag_='1')
        self.add('stage', id_='city-stage', project_id_='city', name_='2026')
        rows = self.query('project_catalog')
        self.assertEqual({r['project_id'] for r in rows}, {'p1', 'city'})
        city = self.query('project_catalog', project_id='city')[0]
        self.assertEqual((city['national_flag'], city['level_name']), ('0', '市级'))
        self.assertEqual(len(self.query('stage_catalog', project_id='city', year='2026')), 1)

    def test_report_relation_accepts_unstaged_performance_and_deduplicates(self):
        self.project()
        self.add('stage',id_='s1',project_id_='p1',name_='2025')
        self.add('module',project_id_='p1',performance_stage_flag_='0')
        self.task('t1')
        self.perf('perf',stage_id_=None)
        for _ in range(2): self.add('task_performance_relation',project_id_='p1',task_id_='t1',performance_id_='perf')
        self.assertEqual(len(self.query('task_performance_links',project_id='p1',year='2025')),1)
        self.assertEqual(self.query('task_performance_links',project_id='p1',year='2026'),[])

    def test_report_sections_exclude_late_feedback_and_keep_empty_sections(self):
        self.project()
        self.add('stage',id_='s1',project_id_='p1',name_='2025')
        self.task('root',level_=1,code_='1')
        self.task('empty',level_=1,code_='2')
        self.task('middle',level_=2,parent_id_='root')
        self.task('leaf',parent_id_='middle',progress_=50)
        for name,when in [('within','2025-12-31'),('late','2026-01-01')]:
            self.add('task_feedback',id_=name,project_id_='p1',task_id_='leaf',date_=when,state_='1')
        rows=self.query('first_task_progress_feedback',project_id='p1',year='2025',start_date='2025-01-01',end_date='2026-01-01')
        self.assertEqual([(r['task_count'],r['period_feedback_count']) for r in rows],[(1,1),(0,0)])
        self.assertIsNone(rows[1]['current_average_progress'])

    def test_cycle_budget_never_adds_annual_or_converts_null_to_zero(self):
        self.project()
        self.fund('cycle',stage_id_=None,budget_total_money_=10)
        self.fund('annual',budget_total_money_=3)
        value=self.query('project_cycle_budget',project_id='p1')[0]
        self.assertEqual(value['cycle_budget_amount'],10)
        self.assertEqual(value['fund_count'],1)
        self.assertIsNone(self.query('project_cycle_budget',project_id='missing')[0]['cycle_budget_amount'])

    def test_task_scope_years_project_flags_and_all_level_exceptions(self):
        self.project()
        self.add('project', id_='p2', name_='任务有效但项目标记不同', high_flag_='0')
        self.add('stage', id_='s1', project_id_='p1', name_='2025')
        self.add('stage', id_='s2', project_id_='p2', name_='2025')
        self.task('t1', progress_=100, state_='2')
        self.task('t2', progress_=None)
        self.task('t3', level_=1, progress_=120)
        self.task('t4', project_id_='p2', stage_id_='s2', progress_=50)
        self.task('wrong-stage', project_id_='p2', stage_id_='s1', progress_=100)
        self.task('cross-tenant', tenant_id_='tenant-b', progress_=100)
        self.task('deleted', delete_flag_='1', progress_=100)
        self.task('placeholder', stage_id_=None, progress_=100)
        self.task('non-high', high_flag_='0', progress_=100)
        self.assertEqual(self.query('task_level_counts', year='2025'), [{'task_level':1,'task_count':1},{'task_level':3,'task_count':3}])
        result = self.query('task_progress_summary', year='2025', level=3)[0]
        self.assertEqual((result['task_count'],result['completed_count'],result['threshold_count']), (3,1,2))
        self.assertEqual(result['avg_progress'],50)
        self.assertEqual(result['missing_progress_count'],1)
        self.assertEqual(self.query('completed_task_count', year='2025')[0]['completed_count'],2)
        self.assertEqual(self.query('task_project_candidates', year='2025',name_pattern='%标记%')[0]['project_id'],'p2')

    def test_approved_material_exists_requires_same_tenant_project_task(self):
        for id in ('a','b','c','d'): self.task(id,progress_=100,level_=1)
        for id, task, state, attachment in [('f1','a','1','["x"]'),('f2','a','1','["x"]'),('f3','b','0','["x"]'),('f4','c','1','[]')]:
            self.add('task_feedback',id_=id,project_id_='p1',task_id_=task,state_=state,attachment_=attachment)
        self.add('task_feedback',id_='wrong-project',project_id_='p2',task_id_='d',state_='1',attachment_='["x"]')
        self.add('task_feedback',id_='wrong-tenant',tenant_id_='tenant-b',project_id_='p1',task_id_='d',state_='1',attachment_='["x"]')
        self.assertEqual(self.query('completed_tasks_without_material')[0],{'completed_count':4,'missing_material_count':3})

    def test_department_dedup_names_null_progress_and_all_level_binding(self):
        self.task('a',progress_=None)
        self.task('b',progress_=100,level_=1)
        for _ in range(2): self.add('task_org',project_id_='p1',task_id_='a',main_org_id_='d1',main_org_name_='部门一')
        self.add('task_org',project_id_='p1',task_id_='a',main_org_id_='d1',main_org_name_='部门一旧名')
        self.add('task_org',project_id_='p1',task_id_='a',main_org_id_='d2',main_org_name_='部门二')
        self.add('task_org',project_id_='p1',task_id_='b',main_org_id_='d2',main_org_name_='部门二')
        self.add('task_org',project_id_='wrong-project',task_id_='a',main_org_id_='bad',main_org_name_='错误部门')
        all_levels={r['department_id']:r for r in self.query('task_department_metrics')}
        self.assertEqual(set(all_levels),{'d1','d2'})
        self.assertEqual(all_levels['d1']['task_count'],1)
        self.assertEqual(all_levels['d1']['completed_count'],0)
        self.assertEqual(all_levels['d1']['max_task_name_variants'],2)
        self.assertEqual(all_levels['d2']['task_count'],2)
        self.assertEqual(all_levels['d2']['avg_progress'],50)
        self.assertEqual(self.query('task_department_metrics',level=3,main_org_id='d2')[0]['completed_count'],0)

    def test_funds_no_double_sum_nulls_and_source_dictionary_codes(self):
        self.project()
        self.add('stage',id_='s1',project_id_='p1',name_='2025')
        self.fund('f1',budget_total_money_=100,execute_total_money_=25,arrival_total_money_=50,budget_centre_money_=60,budget_place_money_=40)
        self.fund('child',level_=2,budget_total_money_=1000)
        self.fund('placeholder',stage_id_=None,budget_total_money_=2000)
        self.fund('deleted',delete_flag_='1',budget_total_money_=3000)
        self.fund('cross-tenant',tenant_id_='tenant-b',budget_total_money_=4000)
        result=self.query('fund_totals',year='2025')[0]
        self.assertEqual((result['fund_count'],result['budget_amount'],result['budget_execution_rate'],result['arrival_rate'],result['arrival_execution_rate']),(1,100,25,50,50))
        sources={r['source_kind']:r for r in self.query('fund_source_amounts',year='2025')}
        self.assertEqual(len(sources),7)
        self.assertEqual(sources['centre']['budget_amount'],60)
        self.assertIsNone(sources['alone']['budget_amount'])
        self.fund('unfilled',budget_total_money_=None,execute_total_money_=5)
        partial=self.query('fund_totals')[0]
        self.assertEqual(partial['budget_amount'],100)
        self.assertEqual(partial['budget_observed_count'],1)
        self.assertEqual(partial['fund_count'],2)
        self.assertIsNone(partial['budget_execution_rate'])

    def test_fund_zero_denominator_and_negative_not_silently_clamped(self):
        self.project()
        self.fund('f1',budget_total_money_=0,execute_total_money_=0)
        result=self.query('fund_totals')[0]
        self.assertEqual(result['budget_amount'],0)
        self.assertIsNone(result['budget_execution_rate'])
        self.fund('adjustment',budget_total_money_=-20,execute_total_money_=-10)
        result=self.query('fund_totals')[0]
        self.assertEqual(result['budget_amount'],-20)
        self.assertEqual(result['budget_execution_rate'],50)

    def test_q16_coverage_uses_distinct_funds_and_preserves_unfilled_diagnostic(self):
        self.project()
        self.task('t',high_flag_='0')
        self.fund('a',task_id_='t',execute_total_money_=None)
        self.fund('b',task_id_=None,execute_total_money_=0,level_=2)
        self.fund('c',task_id_='not-found',execute_total_money_=0,stage_id_=None)
        for _ in range(2): self.add('task_org',project_id_='p1',task_id_='t',main_org_id_='d1',main_org_name_='部门一')
        self.add('task_org',project_id_='p1',task_id_='t',main_org_id_='d2',main_org_name_='部门二')
        result=self.query('fund_department_coverage')[0]
        self.assertEqual((result['total_fund_count'],result['fund_with_task_count'],result['matched_task_count'],result['matched_department_fund_count']),(3,2,1,1))
        self.assertEqual(result['coverage_rate'],33.33)
        self.assertEqual(result['department_count'],2)
        self.assertEqual(result['zero_execute_department_count'],2)
        self.assertEqual(result['all_missing_department_count'],2)

    def test_performance_module_grain_phase_modes_and_duplicate_guard(self):
        for p in ('p1','p2','p3','p4'): self.project(p)
        self.add('module',project_id_='p1',performance_stage_flag_='1')
        self.add('module',project_id_='p2',performance_stage_flag_='0')
        for _ in range(2): self.add('module',project_id_='p3',performance_stage_flag_='1')
        self.add('stage',id_='s1',project_id_='p1',name_='2025')
        self.perf('a',progress_=120,high_flag_='0')
        self.perf('classification',level_=1,progress_=0)
        self.perf('placeholder',stage_id_=None,progress_=0)
        self.perf('b',project_id_='p2',stage_id_=None,progress_=None)
        self.perf('wrong-phase',project_id_='p2',stage_id_='s2',progress_=0)
        self.perf('duplicate-config',project_id_='p3',progress_=0)
        diag={r['project_id']:r for r in self.query('performance_module_status')}
        self.assertEqual(diag['p3']['module_count'],2)
        self.assertEqual(diag['p4']['module_count'],0)
        # 执行端应在以上诊断失败时停止；这里检查底层 SQL 本身不会乘增指标。
        result=self.query('performance_current_summary')[0]
        self.assertEqual((result['performance_count'],result['reached_count'],result['not_reached_count']),(2,1,1))
        self.assertEqual(result['avg_progress'],60)
        self.assertEqual(self.query('performance_stage_summary',project_id='p1',year='2025')[0]['performance_count'],1)

    def test_feedback_returns_versions_without_guessing_latest_snapshot(self):
        self.project()
        self.add('module',project_id_='p1',performance_stage_flag_='0')
        self.perf('a',stage_id_=None)
        for id, date, text in [('f1','2025-01-01','定性目标'),('f2','2025-12-31','新版目标'),('f3','2026-01-01','下一期间提交')]:
            self.add('performance_feedback',id_=id,project_id_='p1',performance_id_='a',state_='1',create_time_=date,year_target_value_=text,total_complete_value_='累计原文')
        result=self.query('performance_feedback_candidates',start_date='2025-01-01',end_date='2026-01-01')
        self.assertEqual(len(result),2)
        self.assertEqual(result[0]['year_target_value'],'定性目标')
        self.assertEqual(result[1]['total_complete_value'],'累计原文')
        self.task('t')
        self.add('task_feedback',id_='t-f1',project_id_='p1',task_id_='t',state_='1',date_='2025-12-31',create_time_='2026-01-02',content_='当期材料',attachment_='["private"]')
        material=self.query('task_feedback_candidates',start_date='2025-01-01',end_date='2026-01-01')
        self.assertEqual(len(material),1)
        self.assertEqual(material[0]['has_attachment'],1)
        self.assertNotIn('attachment_',material[0])

    def test_members_deduplicate_and_keep_role_and_project(self):
        self.project()
        self.task('t')
        for _ in range(2):
            self.add('member',project_id_='p1',user_id_='u',user_name_='示例甲',type_='0')
            self.add('task_member',project_id_='p1',task_id_='t',user_id_='u',user_name_='示例甲',type_='0')
        self.add('task_member',project_id_='p1',task_id_='t',user_id_='u',user_name_='示例甲',type_='1')
        self.add('task_member',project_id_='other',task_id_='t',user_id_='x',user_name_='不能关联',type_='0')
        self.assertEqual(len(self.query('project_leaders')),1)
        self.assertEqual(len(self.query('task_members')),2)
        self.assertEqual(len(self.query('task_members',member_type='0')),1)


if __name__ == '__main__':
    unittest.main()
