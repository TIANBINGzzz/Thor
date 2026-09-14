"""Validate template fidelity and render every page before publication."""
from hashlib import sha256
import os
from pathlib import Path
from secrets import token_urlsafe
import shutil
import subprocess
from zipfile import ZipFile

from lxml import etree

from data_access.context import DataError
from .bindings import NS, document_xml


def check_fidelity(template, output):
    before, after = document_xml(template['_docx']), document_xml(output)
    for slot in template['_slots']:
        if slot['kind']=='static':
            continue
        for xml in (before, after):
            nodes=xml.xpath(slot['locator']['path'],namespaces=NS)
            if len(nodes)!=1: raise DataError('TEMPLATE_STRUCTURE_CHANGED')
            if template.get('clear_fill_markers'):
                from .rendering import clear_fill_markers
                clear_fill_markers(nodes[0])
            for node in nodes[0].xpath('.//w:t[not(ancestor::w:txbxContent)]',namespaces=NS):
                node.text=''
                node.attrib.pop('{http://www.w3.org/XML/1998/namespace}space',None)
    if etree.tostring(before,method='c14n')!=etree.tostring(after,method='c14n'):
        raise DataError('TEMPLATE_STRUCTURE_CHANGED')
    with ZipFile(template['_docx']) as old, ZipFile(output) as new:
        if old.namelist()!=new.namelist(): raise DataError('TEMPLATE_PARTS_CHANGED')
        for name in old.namelist():
            if name!='word/document.xml' and old.read(name)!=new.read(name):
                raise DataError('TEMPLATE_PARTS_CHANGED')
    return {'tables':len(after.xpath('.//w:tbl',namespaces=NS)),
            'sections':len(after.xpath('.//w:sectPr',namespaces=NS)),
            'drawings':len(after.xpath('.//w:drawing',namespaces=NS)),
            'bookmarks':len(after.xpath('.//w:bookmarkStart',namespaces=NS)),
            'unchanged_package_parts':True, 'unchanged_layout_and_run_properties':True,
            'fill_markers_cleared':bool(template.get('clear_fill_markers'))}


def validate_document(template, rendered, environment):
    output=Path(rendered['path'])
    if rendered['missing_count']:
        raise DataError('REPORT_INCOMPLETE')
    fidelity=check_fidelity(template,output) if template.get('preserve_structure') else {}
    folder=output.parent/(output.stem+'-preview')
    folder.mkdir(exist_ok=True)
    pdf=folder/(output.stem+'.pdf')
    pdf.unlink(missing_ok=True)
    renderer=environment.get('CCSDK_REPORT_RENDERER','libreoffice')
    if renderer=='wps' and os.name=='nt':
        command=['powershell','-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',
                 str(Path(__file__).with_name('render_wps.ps1')),str(output),str(pdf)]
    elif renderer=='libreoffice':
        executable=shutil.which('libreoffice') or shutil.which('soffice')
        if not executable: raise DataError('REPORT_RENDERER_UNAVAILABLE')
        command=[executable,'-env:UserInstallation='+ (folder/'office-profile').as_uri(),
                 '--headless','--convert-to','pdf','--outdir',str(folder),str(output)]
    else:
        raise DataError('REPORT_RENDERER_UNAVAILABLE')
    safe={k:v for k,v in environment.items() if k.upper() in {'PATH','SYSTEMROOT','WINDIR','HOME','USERPROFILE','TEMP','TMP','APPDATA','LOCALAPPDATA','LANG','LC_ALL'}}
    try:
        subprocess.run(command,check=True,timeout=180,capture_output=True,env=safe,
                       creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    except (OSError,subprocess.SubprocessError):
        raise DataError('REPORT_RENDER_FAILED') from None
    import pypdfium2 as pdfium
    pages=[]
    document=pdfium.PdfDocument(pdf)
    try:
        for number in range(1,len(document)+1):
            page=document[number-1]
            bitmap=None
            try:
                image=folder/f'page-{number}.png'
                bitmap=page.render(scale=1.25)
                bitmap.to_pil().save(image)
                pages.append(str(image))
            finally:
                if bitmap is not None: bitmap.close()
                page.close()
        if not pages: raise DataError('REPORT_RENDER_EMPTY')
    finally:
        document.close()
    return {'validation_ref':'validation_'+token_urlsafe(18), 'document_sha256':sha256(output.read_bytes()).hexdigest(),
            'fidelity':fidelity, 'page_count':len(pages), 'pages':pages, 'pdf_path':str(pdf),
            'visual_review':'rendered_pages_require_review'}


def validated_plan(planner, plan_ref, validation_ref):
    if plan_ref != planner.latest:
        raise DataError('PLAN_SUPERSEDED')
    plan = planner.plans[plan_ref]
    validation = plan.get('validation', {})
    rendered = plan.get('rendered', {})
    if (not validation_ref or validation.get('validation_ref') != validation_ref or not rendered
            or sha256(Path(rendered['path']).read_bytes()).hexdigest() != validation.get('document_sha256')):
        raise DataError('REPORT_VALIDATION_REQUIRED')
    return plan, validation


def record_page_review(validation, page_numbers, passed, notes):
    requested = set(page_numbers)
    if not requested or not requested <= set(validation.get('pages_read', [])):
        raise DataError('REPORT_PAGES_NOT_READ')
    reviews = validation.setdefault('page_reviews', {})
    for number in requested:
        reviews[str(number)] = {'passed': passed, 'notes': notes}
    complete = all(reviews.get(str(i), {}).get('passed') for i in range(1, validation['page_count'] + 1))
    validation['visual_review'] = 'passed' if complete else 'review_required'
    return {'reviewed': len(reviews), 'page_count': validation['page_count'], 'visual_review': validation['visual_review']}
