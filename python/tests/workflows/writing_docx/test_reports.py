"""Hybrid report editing against a current document, not mandatory template slots."""

import asyncio
from copy import deepcopy
from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path
import unittest
from zipfile import ZipFile

from docx import Document
from lxml import etree

from data_access.context import DataError
from runtime.data_services import RunServices
from workflows.writing_docx.document_map import build_document_map, document_xml, NS
from workflows.writing_docx.template_assets import load_template
from workflows.writing_docx.report_locations import resolve_target
from workflows.writing_docx.report_planner import ReportPlanner
from workflows.writing_docx.report_renderer import render, validate_drafts, replace_paragraph
from workflows.writing_docx.report_validator import check_fidelity, validate_document, validated_plan, record_page_review
from tests import test_data_access as fixture

save = fixture.save


class ReportingTests(unittest.TestCase):
    setUp = fixture.DataAccessTests.setUp
    make_executor = fixture.DataAccessTests.make_executor
    save_connections = fixture.DataAccessTests.save_connections
    school = fixture.DataAccessTests.school

    def template(self):
        directory = self.root/'templates/demo'
        directory.mkdir(parents=True)
        document = Document()
        document.add_heading('Summary', 1)
        table = document.add_table(rows=1, cols=2)
        table.cell(0, 0).text = 'Total'
        table.cell(0, 1).text = 'pending'
        document.add_paragraph('Original narrative')
        document.add_heading('Next section', 1)
        document.add_paragraph('Static footer')
        path = directory/'template.docx'
        document.save(path)
        document_map = build_document_map('demo', 1, path)
        for index, item in enumerate(document_map['locations']):
            item.update(node_type='scalar' if item['table'] else 'narrative', required=True,
                        section_key='summary' if index < 4 else 'next')
        save(directory/'document-map.json', document_map)
        save(directory/'report-data-plan.json', {'plan_version':1, 'template_key':'demo', 'template_version':1,
            'datasets':[{'dataset_key':'total', 'source_role':'sales', 'domain':'sales', 'scope_role':'school',
                         'query_id':'total', 'parameter_bindings':{}}]})
        save(directory/'template.json', {'template_key':'demo', 'name':'Demo', 'enabled':True, 'capabilities':['qa'],
            'version':1, 'assets':{'docx':{'file':path.name, 'sha256':sha256(path.read_bytes()).hexdigest()},
                'writing_guide':'writing-guide.md', 'document_map':'document-map.json', 'data_plan':'report-data-plan.json'},
            'data':{'source_roles':{'sales':'first'}, 'scope_roles':{'sales':['school']}},
            'report':{'parameters':{'type':'object'}, 'file_name':'report.docx'},
            'output_policy':{'preserve_structure':True, 'clear_fill_markers':True}})
        (directory/'writing-guide.md').write_text('DEMO GUIDE', encoding='utf-8')
        return load_template('demo', 'qa', directory.parent)

    def reload(self, template):
        return load_template('demo', 'qa', template['_directory'].parent)

    async def planner(self, template=None, dataset_keys=None):
        template = template or self.template()
        services = RunServices(['first', 'second'], env=self.env, catalog=self.catalog)
        services.executor = self.executor
        planner = ReportPlanner(services, template)
        services.report = planner
        scope = self.school()
        result = await planner.prepare({'years':['2025'], 'period_mode':'annual', 'timezone':'Asia/Shanghai'},
                                       {'sales':{'school':scope}}, dataset_keys)
        await asyncio.gather(*list(planner.tasks))
        return planner, planner.plans[result['plan_ref']], scope

    @staticmethod
    def gap(target, text='Evaluate coverage. Records missing. Collect dated records.'):
        return {'target':target, 'text':text, 'evidence_refs':[], 'evidence_state':'none',
                'analysis_basis':'Evaluate coverage.', 'gap':'Records missing.', 'next_action':'Collect dated records.'}

    def test_partial_edits_do_not_require_map_coverage_or_auto_fill(self):
        async def scenario():
            planner, plan, _ = await self.planner()
            data = planner.get(plan['plan_ref'], 'summary')
            self.assertIn('location_hints', data)
            self.assertNotIn('slots', data)
            self.assertNotIn('locator', data['location_hints'][0])
            with self.assertRaisesRegex(DataError, 'REPORT_EDITS_REQUIRED'):
                await planner.render(plan['plan_ref'], [])
            draft = self.gap({'original_text':'Original narrative'})
            output = await planner.render(plan['plan_ref'], [draft])
            self.assertEqual(output['status'], 'rendered_with_data_gaps')
            self.assertGreater(plan['coverage']['unedited_recommendations'], 0)
            self.assertEqual(Document(output['path']).tables[0].cell(0, 1).text, 'pending')
            self.assertTrue(check_fidelity(planner.template, output['path'], output['edits'])['matches_declared_edits'])
            self.assertTrue(document_xml(output['path']).xpath('.//w:color[@w:val="FFC000"]', namespaces=NS))
            await planner.services.close()
        asyncio.run(scenario())

    def test_dataset_subset_empty_and_deduplication(self):
        async def scenario():
            template = self.template()
            duplicate = deepcopy(template['_bindings']['datasets'][0])
            duplicate['dataset_key'] = 'repeated_total'
            template['_bindings']['datasets'].append(duplicate)
            planner, plan, scope = await self.planner(template, [])
            self.assertEqual(plan['nodes'], [])
            params, scopes = plan['report_parameters'], {'sales':{'school':scope}}
            for selected, expected in ((['total'], ['total']), (None, ['total', 'repeated_total'])):
                result = await planner.prepare(params, scopes, selected)
                await asyncio.gather(*list(planner.tasks))
                current = planner.plans[result['plan_ref']]
                self.assertEqual(len(current['nodes']), 1)
                self.assertEqual(current['nodes'][0]['dataset_keys'], expected)
                self.assertEqual((await planner.prepare(params, scopes, selected))['plan_ref'], result['plan_ref'])
            with self.assertRaisesRegex(DataError, 'DATASET_INVALID'):
                await planner.prepare(params, scopes, ['unknown'])
            with self.assertRaisesRegex(DataError, 'PLAN_SUPERSEDED'):
                planner.save_drafts(plan['plan_ref'], [])
            await planner.services.close()
        asyncio.run(scenario())

    def test_format_changes_do_not_require_map_rebuild_but_change_revision(self):
        template = self.template()
        document = Document(template['_docx'])
        document.paragraphs[1].runs[0].bold = True
        document.save(template['_docx'])
        revised = self.reload(template)
        self.assertNotEqual(template['_revision'], revised['_revision'])
        self.assertEqual(revised['_map_status']['unmatched_annotations'], 0)
        self.assertIn('DOCX_BASELINE_CHANGED', revised['_warnings'])

    def test_stale_map_only_keeps_unique_text_matches(self):
        template = self.template()
        document = Document(template['_docx'])
        document.paragraphs[1].insert_paragraph_before('Added paragraph')
        document.paragraphs[-1].text = 'Revised footer'
        document.save(template['_docx'])
        revised = self.reload(template)
        self.assertEqual(resolve_target(revised['_locations'], {'original_text':'Original narrative'})['annotation']['section_key'], 'summary')
        self.assertNotIn('annotation', resolve_target(revised['_locations'], {'original_text':'Revised footer'}))
        self.assertIn('DOCUMENT_MAP_PARTIALLY_MATCHED', revised['_warnings'])
        regenerated = build_document_map('demo', 1, revised['_docx'], template['_document_map']['locations'])
        self.assertEqual(len(regenerated['locations']), 7)
        self.assertEqual(len({item['location_id'] for item in regenerated['locations']}), 7)

    def test_absent_missing_and_malformed_maps_are_optional(self):
        template = self.template()
        path = template['_directory']/'document-map.json'
        path.unlink()
        self.assertIn('DOCUMENT_MAP_MISSING', self.reload(template)['_warnings'])
        for value in ([], {'locations':[]}, {'map_version':1, 'locations':None}):
            save(path, value)
            self.assertIn('DOCUMENT_MAP_IGNORED', self.reload(template)['_warnings'])
        broken = deepcopy(template['_document_map'])
        broken['locations'][0]['locator'] = {}
        save(path, broken)
        self.assertIn('DOCUMENT_MAP_IGNORED', self.reload(template)['_warnings'])
        config_path = template['_directory']/'template.json'
        config = json.loads(config_path.read_text())
        del config['assets']['document_map']
        del config['assets']['data_plan']
        save(config_path, config)
        revised = self.reload(template)
        self.assertEqual(revised['_bindings']['datasets'], [])
        self.assertEqual(len(revised['_locations']), 6)

    def test_ambiguous_text_requires_current_target_and_duplicate_edits_fail(self):
        async def scenario():
            template = self.template()
            document = Document(template['_docx'])
            document.add_paragraph('Original narrative')
            document.save(template['_docx'])
            planner, plan, _ = await self.planner(self.reload(template), [])
            with self.assertRaisesRegex(DataError, 'DRAFT_LOCATION_AMBIGUOUS'):
                planner.save_drafts(plan['plan_ref'], [self.gap({'original_text':'Original narrative'})])
            target = {'section':'Summary', 'original_text':'Original narrative'}
            planner.save_drafts(plan['plan_ref'], [self.gap(target)])
            with self.assertRaisesRegex(DataError, 'DRAFT_DUPLICATE'):
                planner.save_drafts(plan['plan_ref'], [self.gap(target), self.gap(target)])
            for item in plan['locations']:
                if item['text'] == 'Original narrative':
                    self.assertNotIn('annotation', item)
            await planner.services.close()
        asyncio.run(scenario())

    def test_unannotated_table_and_paragraph_splits_preserve_unrelated_parts(self):
        async def scenario():
            template = self.template()
            (template['_directory']/'document-map.json').unlink()
            planner, plan, _ = await self.planner(self.reload(template), [])
            drafts = [self.gap({'section':'Summary', 'original_text':'Original narrative'},
                               'Evaluate coverage.\n\nRecords missing. Collect dated records.'),
                      self.gap({'table':{'table_id':'T01', 'row':1, 'column':2, 'paragraph':1}}, 'Records missing.'),
                      self.gap({'original_text':'Static footer'})]
            output = await planner.render(plan['plan_ref'], drafts)
            document = Document(output['path'])
            self.assertEqual(document.paragraphs[1].text, 'Evaluate coverage.')
            self.assertEqual(document.paragraphs[2].text, 'Records missing. Collect dated records.')
            self.assertEqual(document.paragraphs[-1].text, drafts[-1]['text'])
            self.assertEqual(document.tables[0].cell(0, 1).text, 'Records missing.')
            self.assertTrue(check_fidelity(planner.template, output['path'], output['edits'])['unchanged_package_parts'])
            document.paragraphs[0].runs[0].bold = True
            document.save(output['path'])
            with self.assertRaisesRegex(DataError, 'TEMPLATE_STRUCTURE_CHANGED'):
                check_fidelity(planner.template, output['path'], output['edits'])
            await planner.services.close()
        asyncio.run(scenario())

    def test_run_document_drift_rejects_writes(self):
        async def scenario():
            planner, plan, _ = await self.planner()
            document = Document(planner.template['_docx'])
            document.add_paragraph('Changed after planning')
            document.save(planner.template['_docx'])
            with self.assertRaisesRegex(DataError, 'TEMPLATE_MISMATCH'):
                await planner.render(plan['plan_ref'], [self.gap({'original_text':'Original narrative'})])
            await planner.services.close()
        asyncio.run(scenario())

    def test_merged_cells_and_nested_tables_use_physical_coordinates(self):
        template = self.template()
        document = Document(template['_docx'])
        table = document.add_table(rows=2, cols=2)
        table.cell(0, 0).merge(table.cell(1, 0)).text = 'Vertical merged'
        table.cell(0, 1).add_table(rows=1, cols=1).cell(0, 0).text = 'Nested'
        document.save(template['_docx'])
        locations = self.reload(template)['_locations']
        nested = resolve_target(locations, {'original_text':'Nested'})
        self.assertEqual(nested['table']['table_id'], 'T03')
        with self.assertRaisesRegex(DataError, 'DRAFT_MERGED_CELL_CONTINUATION'):
            resolve_target(locations, {'table':{'table_id':'T02', 'row':2, 'column':1, 'paragraph':1}})

    def test_splits_keep_styles_section_breaks_and_do_not_duplicate_bookmarks(self):
        from workflows.writing_docx.report_renderer import compose_document
        template = self.template()
        document = Document(template['_docx'])
        paragraph = document.paragraphs[1]
        paragraph.runs[0].bold = True
        properties = paragraph._p.get_or_add_pPr()
        etree.SubElement(properties, '{'+NS['w']+'}sectPr')
        marker = etree.SubElement(paragraph._p, '{'+NS['w']+'}bookmarkStart')
        marker.set('{'+NS['w']+'}id', '100')
        marker.set('{'+NS['w']+'}name', 'original')
        document.save(template['_docx'])
        template = self.reload(template)
        xml = compose_document(template, [self.gap({'original_text':'Original narrative'}, 'First\n\nSecond')])
        body = xml.find('w:body', NS)
        paragraphs = body.findall('w:p', NS)
        self.assertEqual(len(xml.xpath('.//w:bookmarkStart', namespaces=NS)), 1)
        self.assertIsNone(paragraphs[1].find('w:pPr/w:sectPr', NS))
        self.assertIsNotNone(paragraphs[2].find('w:pPr/w:sectPr', NS))
        self.assertIsNotNone(paragraphs[2].find('w:r/w:rPr/w:b', NS))
        with self.assertRaisesRegex(DataError, 'PARAGRAPH_SPLIT_UNSUPPORTED'):
            compose_document(template, [self.gap({'original_text':'Summary'}, 'First\n\nSecond')])

    def test_current_locations_paginate_with_cursor_bound_to_section_and_filter(self):
        async def scenario():
            template = self.template()
            document = Document(template['_docx'])
            for _ in range(60):
                document.add_paragraph('Extra paragraph')
            document.save(template['_docx'])
            planner, plan, _ = await self.planner(self.reload(template), [])
            first = planner.get(plan['plan_ref'], 'Next section')
            self.assertEqual(len(first['location_hints']), 50)
            second = planner.get(plan['plan_ref'], 'Next section', first['cursor'])
            self.assertEqual(len(second['location_hints']), 10)
            with self.assertRaisesRegex(DataError, 'CURSOR_INVALID'):
                planner.get(plan['plan_ref'], 'summary', first['cursor'])
            with self.assertRaisesRegex(DataError, 'CURSOR_INVALID'):
                planner.get(plan['plan_ref'], 'Next section', first['cursor'], True)
            await planner.services.close()
        asyncio.run(scenario())

    def test_supplemental_evidence_with_no_prefetch_stays_inside_bound_scope(self):
        async def scenario():
            planner, plan, scope = await self.planner(dataset_keys=[])
            result = self.executor.execute_query_spec('first', 'sales', 'total', {}, scope)
            draft = {'target':{'original_text':'Original narrative'}, 'text':'Recorded total: 10.',
                     'evidence_state':'supported', 'evidence_refs':[result['result_ref']]}
            # Optional map annotations cannot replace the Run's authoritative data scope.
            for item in plan['locations']:
                if item['text'] == 'Original narrative':
                    item['annotation']['scope_role'] = 'historical_scope'
            planner.save_drafts(plan['plan_ref'], [draft])
            record = self.executor.results.get(result['result_ref'])
            foreign = self.executor.execute_query_spec('second', 'sales', 'total', {}, self.school(source='second'))
            wrong_scope = self.executor.execute_query_spec('first', 'sales', 'total', {}, self.school())
            truncated = self.executor.results.save([{'total':10}], {**record['metadata'], 'complete':False}, record['output'])
            for ref in (foreign['result_ref'], wrong_scope['result_ref'], truncated, 'another_run'):
                with self.subTest(ref=ref), self.assertRaisesRegex(DataError, 'EVIDENCE_REQUIRED'):
                    planner.save_drafts(plan['plan_ref'], [{**draft, 'evidence_refs':[ref]}])
            output = await planner.render(plan['plan_ref'], [])
            self.assertFalse(document_xml(output['path']).xpath('.//w:color[@w:val="FFC000"]', namespaces=NS))
            await planner.services.close()
        asyncio.run(scenario())

    def test_evidence_states_gaps_numbers_and_private_columns(self):
        async def scenario():
            planner, plan, scope = await self.planner()
            draft = self.gap({'original_text':'Original narrative'})
            planner.save_drafts(plan['plan_ref'], [draft])
            with self.assertRaisesRegex(DataError, 'EVIDENCE_GAP_REQUIRED'):
                planner.save_drafts(plan['plan_ref'], [{**draft, 'text':'Records missing.'}])
            result = self.executor.execute_query_spec('first', 'sales', 'total', {}, scope)
            limited = {**draft, 'text':'Recorded 10. Records missing.', 'evidence_state':'limited',
                       'evidence_refs':[result['result_ref']]}
            planner.save_drafts(plan['plan_ref'], [limited])
            with self.assertRaisesRegex(DataError, 'EVIDENCE_STATE_CONFLICT'):
                planner.save_drafts(plan['plan_ref'], [{**limited, 'evidence_state':'supported'}])
            with self.assertRaisesRegex(DataError, 'DRAFT_NUMBER_UNSUPPORTED'):
                planner.save_drafts(plan['plan_ref'], [{**limited, 'text':'Recorded 999. Records missing.'}])
            record = self.executor.results.get(result['result_ref'])
            empty = self.executor.results.save([], record['metadata'], record['output'])
            with self.assertRaisesRegex(DataError, 'EVIDENCE_REQUIRED'):
                planner.save_drafts(plan['plan_ref'], [{**limited, 'evidence_refs':[empty]}])
            private = self.executor.results.save([{'total':10, 'internal_id':999}], record['metadata'],
                        [*record['output'], {'name':'internal_id', 'visibility':'internal_only'}])
            with self.assertRaisesRegex(DataError, 'DRAFT_NUMBER_UNSUPPORTED'):
                planner.save_drafts(plan['plan_ref'], [{**limited, 'text':'Recorded 999. Records missing.', 'evidence_refs':[private]}])
            await planner.services.close()
        asyncio.run(scenario())

    def test_report_parameters_can_support_title_but_unknown_refs_fail(self):
        async def scenario():
            planner, plan, _ = await self.planner(dataset_keys=[])
            draft = {'target':{'original_text':'Summary'}, 'text':'Report 2025', 'evidence_refs':[],
                     'parameter_refs':['years'], 'evidence_state':'supported'}
            planner.save_drafts(plan['plan_ref'], [draft])
            with self.assertRaisesRegex(DataError, 'EVIDENCE_REQUIRED'):
                planner.save_drafts(plan['plan_ref'], [{**draft, 'parameter_refs':['unknown']}])
            await planner.services.close()
        asyncio.run(scenario())

    def test_real_placeholders_block_validation_not_unedited_map_count(self):
        async def scenario():
            template = self.template()
            document = Document(template['_docx'])
            document.tables[0].cell(0, 1).text = '{{unknown_value}}'
            document.add_paragraph('__')
            document.sections[0].header.paragraphs[0].text = '键入章标题'
            document.save(template['_docx'])
            planner, plan, _ = await self.planner(self.reload(template), [])
            output = await planner.render(plan['plan_ref'], [self.gap({'original_text':'Original narrative'})])
            self.assertEqual(output['missing_count'], 3)
            with self.assertRaisesRegex(DataError, 'REPORT_INCOMPLETE'):
                validate_document(planner.template, output, {})
            await planner.services.close()
        asyncio.run(scenario())

    def test_saved_edits_invalidate_previous_render_and_review(self):
        async def scenario():
            planner, plan, _ = await self.planner()
            draft = self.gap({'original_text':'Original narrative'})
            await planner.render(plan['plan_ref'], [draft])
            plan['validation'] = {'validation_ref':'old'}
            planner.save_drafts(plan['plan_ref'], [draft])
            self.assertNotIn('rendered', plan)
            self.assertNotIn('validation', plan)
            with self.assertRaisesRegex(DataError, 'REPORT_VALIDATION_REQUIRED'):
                validated_plan(planner, plan['plan_ref'], 'old')
            await planner.services.close()
        asyncio.run(scenario())

    def test_mixed_runs_empty_paragraph_and_bookmarks_preserved(self):
        markup = '<w:p xmlns:w="'+NS['w']+'"><w:pPr/><w:r><w:rPr><w:b/></w:rPr><w:t>abc</w:t></w:r><w:bookmarkStart w:id="1" w:name="x"/><w:r><w:t>def</w:t></w:r><w:bookmarkEnd w:id="1"/></w:p>'
        for text in ('abc123def', 'ABCdef', 'abcdefXYZ', '', 'hello world', 'aXYcdeZ'):
            node = etree.fromstring(markup)
            replace_paragraph(node, text)
            self.assertEqual(''.join(node.xpath('.//w:t/text()', namespaces=NS)), text)
            self.assertEqual(len(node.xpath('.//w:b|.//w:bookmarkStart|.//w:bookmarkEnd', namespaces=NS)), 3)
        node = etree.fromstring('<w:p xmlns:w="'+NS['w']+'"/>')
        replace_paragraph(node, 'Filled')
        self.assertEqual(node.xpath('.//w:t/text()', namespaces=NS), ['Filled'])

    def test_full_template_reads_without_mandatory_slot_contract(self):
        template = load_template('szpt-midterm', 'document-writing')
        self.assertEqual(template['_map_status']['matched_annotations'], 3503)
        executor = self.make_executor()
        executor.context = replace(executor.context, capability_ref='document-writing')
        target = next(item for item in template['_locations'] if item.get('annotation', {}).get('node_type') == 'narrative')
        plan = {'plan_ref':'full-template', 'report_parameters':{'years':['2025']},
                'locations':template['_locations'], 'evidence_scopes':[]}
        output = render(template, plan, [self.gap({'location_hint':target['location_hint']})], executor)
        before, after = document_xml(template['_docx']), document_xml(output['path'])
        for tag in ('tbl', 'tr', 'tc', 'p', 'sectPr', 'drawing'):
            self.assertEqual(len(before.xpath(f'.//w:{tag}', namespaces=NS)), len(after.xpath(f'.//w:{tag}', namespaces=NS)))
        self.assertEqual(len(after.xpath('.//w:tbl', namespaces=NS)), 40)

    def test_report_mcp_publish_gate_and_page_images(self):
        async def scenario():
            from base64 import b64decode
            from workflows.writing_docx.tools import create_reports_server
            planner, plan, _ = await self.planner()
            ref = plan['plan_ref']
            output = await planner.render(ref, [self.gap({'original_text':'Original narrative'})])
            planner.services.artifact_directories = {'deliverables_directory':str(self.root/'deliverables'),
                                                     'session_directory':str(self.root/'session')}
            page = self.root/'page.png'
            page.write_bytes(b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aX1sAAAAASUVORK5CYII='))
            plan['validation'] = {'validation_ref':'v', 'document_sha256':sha256(Path(output['path']).read_bytes()).hexdigest(),
                                  'page_count':2, 'pages':[str(page), str(page)], 'visual_review':'rendered_pages_require_review'}
            entry = create_reports_server(planner.services)['instance'].get_request_handler('tools/call')
            async def call(name, **args):
                return await entry.handler(None, entry.params_type(name=name, arguments=args))
            args = {'plan_ref':ref, 'validation_ref':'v'}
            config = json.loads((await call('get_report_data')).content[0].text)
            self.assertIn('recommended_datasets', config)
            saved = json.loads((await call('save_report_sections', plan_ref=ref,
                section_drafts=[self.gap({'original_text':'Original narrative'})])).content[0].text)
            self.assertEqual(saved['saved'], 1)
            rendered = json.loads((await call('render_report', plan_ref=ref, section_drafts=[])).content[0].text)
            self.assertEqual(rendered['missing_count'], 0)
            self.assertGreater(rendered['coverage']['unedited_recommendations'], 0)
            plan['validation'] = {'validation_ref':'v', 'document_sha256':sha256(Path(output['path']).read_bytes()).hexdigest(),
                                  'page_count':2, 'pages':[str(page), str(page)], 'visual_review':'rendered_pages_require_review'}
            self.assertIn('REPORT_VISUAL_REVIEW_REQUIRED', (await call('publish_report', **args)).content[0].text)
            self.assertIn('REPORT_PAGES_NOT_READ', (await call('review_report_pages', **args, page_numbers=[1], passed=True, notes='not read')).content[0].text)
            images = await call('read_report_pages', **args, page_numbers=[1, 2])
            self.assertEqual(sum(c.type == 'image' for c in images.content), 2)
            await call('review_report_pages', **args, page_numbers=[1], passed=True, notes='checked')
            self.assertIn('REPORT_VISUAL_REVIEW_REQUIRED', (await call('publish_report', **args)).content[0].text)
            await call('review_report_pages', **args, page_numbers=[2], passed=True, notes='checked')
            result = json.loads((await call('publish_report', **args)).content[0].text)
            self.assertTrue(result['published'])
            self.assertTrue((self.root/'deliverables/report.docx').exists())
            await planner.services.close()
        asyncio.run(scenario())


if __name__ == '__main__':
    unittest.main()
