"""Register the original template's reviewed 2025 reporting contract, without editing its DOCX."""
import json
from pathlib import Path
import re
import sys

DIRECTORY=Path(__file__).resolve().parent
ROOT=DIRECTORY.parents[4]
sys.path.insert(0,str(ROOT/'python'))
from workflows.writing_docx.bindings import NS, document_xml


def configure():
    def load(name): return json.loads((DIRECTORY/name).read_text(encoding='utf-8'))
    def save(name,data): (DIRECTORY/name).write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    template,bindings=load('template.json'),load('query-bindings.json')
    xml=document_xml(DIRECTORY/template['docx_file'])
    paragraphs=xml.xpath('.//w:p',namespaces=NS)
    positions={xml.getroottree().getpath(p):i for i,p in enumerate(paragraphs,1)}
    definitions=[('project_catalog',{'name_pattern':None}),('task_tree',{}),('task_progress_summary',{'level':3,'threshold':50}),
                 ('report_task_sections',{}),('task_feedback_candidates',{}),('fund_totals',{}),
                 ('fund_source_amounts',{}),('report_cycle_budget',{}),('report_task_performance_links',{}),
                 ('performance_tree',{})]
    datasets=[]
    from data_access.catalog import Catalog
    catalog=Catalog()
    for role in ('group_a','group_b'):
        for query,values in definitions:
            spec=catalog.spec('schoolDoubleHigh','hpm',query)
            params={k:{'from':'literal','value':v} for k,v in values.items()}
            if 'year' in spec['parameters']:
                params['year']={'from':'report_parameter','key':'years','expand':'each'}
            datasets.append({'dataset_key':role+'_'+query,'source_role':'hpm','domain':'hpm','scope_role':role,
                'query_id':query,'parameter_bindings':params,'section_keys':['overview','school',role,'measures','experience','improvements']})
    def evidence(role):
        roles=[role] if role in ('group_a','group_b') else ['group_a','group_b']
        return [r+'_'+q for r in roles for q,_ in definitions]
    def role_for(position):
        if 2211<=position<3238 or 4718<=position<4852: return 'group_a'
        if 3238<=position<4342 or position>=4852: return 'group_b'
        return 'school'
    def section_for(position):
        if position<512: return 'overview'
        if position<2211: return 'school'
        if position<3238: return 'group_a'
        if position<4342: return 'group_b'
        if position<4377: return 'measures'
        if position<4384: return 'experience'
        if position<4394: return 'improvements'
        return 'appendix'
    groups={}
    for file in bindings['slot_files']:
        group=load(file)
        for slot in group['slots']:
            position=positions[slot['locator']['path']]
            node=paragraphs[position-1]
            text=''.join(node.xpath('.//w:t/text()',namespaces=NS))
            role=role_for(position)
            table=slot['slot_key'].startswith('T')
            if table:
                n=int(slot['slot_key'][1:3])
                role='group_a' if 17<=n<=27 else 'group_b' if 28<=n<=39 else 'school'
            slot['scope_role']=role
            slot['section_key']=slot['slot_key'][:3] if table else section_for(position)
            slot['template_text']=text
            for field in ('dataset_key','field','resolution','text_template','values','evidence_datasets','write_instruction'):
                slot.pop(field,None)
            rules=set(slot['source_rules'])
            dynamic=bool(re.search(r'_{2,}|【[^】]+】',text))
            replacements={'通信技术专业群':'${group_a_name}','电子信息工程技术专业群':'${group_b_name}',
                '【报告日期】':'${as_of}','【统计期间】':'${year}年度','【报告年度】':'${year}',
                '【预算期间】':'${year}年度','【统计截止日期】':'${as_of}', '中期自评报告':'${year}年度自评报告'}
            revised=text
            values={}
            for old,new in replacements.items():
                if old in revised:
                    revised=revised.replace(old,new)
            for role_key in ('group_a','group_b'):
                if '${'+role_key+'_name}' in revised:
                    values[role_key+'_name']={'dataset_key':role_key+'_project_catalog','field':'project_name'}
            for key,param in [('year','years'),('as_of','as_of')]:
                if '${'+key+'}' in revised: values[key]={'report_parameter':param}
            if not table and position<4394 and (slot['kind']=='narrative' or dynamic and 'N' in rules):
                slot.update(kind='narrative',required=True,evidence_datasets=evidence(role),
                    write_instruction='按本段原有主题撰写真实的年度自评正文，使用当前项目名称。学校独立项目未绑定，不得把两专业群当全校。当前任务/资金登记值必须明确标为当前值；无期内反馈时说明评价限制，不得声称已建成、获奖、达标、发布制度。原有一级建设标题保留为模板核验维度，不能把新旧名称硬认作同一指标。不要重复占位提示，分段讨论具体事项与核验结论；改进措施写建议而非已执行事实。')
            elif ('E' in rules or 'E+X' in rules) and position>=4394:
                revised=re.sub(r'_{2,}', '/', text).replace('【材料待补】','')
                slot.update(kind='scalar',required=True,resolution={'text':revised+'（本期未提供佐证）',
                    'reason':'period_material_unavailable','require_empty':[r+'_task_feedback_candidates' for r in (['group_a','group_b'] if role=='school' else [role])]},
                    evidence_datasets=evidence(role))
            elif table and (slot['kind']!='static' or dynamic):
                if rules=={'S'} or slot['business_context'].endswith((' / 分值',' / 得分')):
                    slot.update(kind='scalar',required=False,intentional_blank=True)
                else:
                    revised=re.sub(r'_{2,}|【[^】]+】','/',revised)
                    slot.update(kind='scalar',required=True,resolution={'text':revised,'reason':
                        'school_project_unbound' if role=='school' else 'historical_metric_unavailable',
                        'require_empty':[] if role=='school' else [role+'_report_task_performance_links',role+'_task_feedback_candidates']},evidence_datasets=evidence(role))
            elif revised!=text:
                slot.update(kind='scalar',required=True,text_template=revised,values=values)
            else:
                slot.update(kind='static',required=False)
            slot['binding_status']='registered' if slot['kind']!='static' else 'static'
            groups.setdefault(file,group)
    for file,group in groups.items(): save(file,group)
    bindings.update(version=3,template_version=2,status='bound_with_explicit_data_gaps',datasets=datasets)
    template.update(version=2,preserve_structure=True,clear_fill_markers=True,scope_roles={'hpm':['group_a','group_b']},
                    missing_policy='reject',file_name='双高计划${years}年度自评报告.docx')
    template['parameters']['properties']['years']['maxItems']=1
    template['parameters']['properties']['period_mode']={'const':'annual'}
    template['parameters']['required']=list(dict.fromkeys(template['parameters']['required']+['as_of']))
    template['outline']=[{'section_key':key,'title':title} for key,title in [
        ('overview','一、总体实现程度'),('school','二、学校层面任务及绩效指标完成情况'),
        ('group_a','三、专业群层面任务及绩效指标完成情况（一）'),('group_b','三、专业群层面任务及绩效指标完成情况（二）'),
        ('measures','四、实现绩效目标采取的措施'),('experience','五、特色经验与做法'),('improvements','六、问题与改进措施'),('appendix','附件：佐证材料目录清单')]]
    save('template.json',template)
    save('query-bindings.json',bindings)
    print(json.dumps({'datasets':len(datasets),'slots':sum(len(g['slots']) for g in groups.values()),
                      'narratives':sum(s['kind']=='narrative' for g in groups.values() for s in g['slots'])}))


if __name__=='__main__': configure()
