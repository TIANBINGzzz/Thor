"""隔离源码快照，经真实 HTTP/SSE 比较精简撰写提示词；不生成或修正文稿。"""

import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import uuid
import zipfile

import httpx

ROOT = Path(__file__).resolve().parents[1]
QUESTION = (
    '使用提供的模板和schoolDoubleHigh数据源，完成重庆建筑2026年度双高计划中期自评报告，'
    '统计截止日为2026年9月18日，范围为全校及实际建设专业群。'
    '按章节分批撰写并保存，持续推进至全文完成；自行决定读取、查询、编辑和核验方式。'
    '事实须有依据，区分统计期间与当前状态，资料不足时简明说明。'
    '保留模板全部章节、表格、附件结构和样式，另存新稿，跳过封面两页。'
    '最终交付经过内容及版式核验的DOCX和PDF。'
)
SEMANTICS = """关键业务口径：
- 专业群取实际项目目录，国家级和市级分别披露，演示项目不计入建设成果；固定国双高查询的筛选不表示市级未获授权。
- 年度使用各项目实际阶段名称；当前台账不是截止日历史快照，年度与全建设期分别表述。
- 建设任务树和绩效分类树不同；任务进度、按条数完成率和自评得分不能替代，缺评分办法不能推算得分。
- 资金单位万元，按适用一级节点汇总，不叠加父子节点；年度资金与无阶段的全建设期预算分开，比率分母须对应。
- 反馈是成果线索，条数不等于成果数，认定结论须有证据；NULL、零、无记录与查询失败分别处理。
"""


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def prepare(output, variant):
    output.mkdir(parents=True, exist_ok=False)
    repo = output / 'repo'
    archive = output / 'source.zip'
    subprocess.run(['git', 'archive', '--format=zip', '-o', str(archive), 'HEAD'], cwd=ROOT, check=True)
    with zipfile.ZipFile(archive) as source:
        source.extractall(repo)
    archive.unlink()
    # 测试进程使用私有凭据副本，绝不把凭据写入结果或提示词。
    shutil.copy2(ROOT / '.env', repo / '.env')
    shutil.copy2(ROOT / 'config/databases.json', repo / 'config/databases.json')
    workflow = repo / '.claude/workflows/writing-docx'
    env = ROOT / '.claude/workflows/writing-docx/workflow.env'
    if env.exists():
        shutil.copy2(env, workflow / 'workflow.env')
    instructions = '依据本轮用户要求自主完成报告。可通过data工具按需获取数据结构、查询定义和业务语义。\n'
    if variant == 'B':
        instructions += SEMANTICS
    (workflow / 'instructions.md').write_text(instructions, encoding='utf-8')
    config = repo / 'python/runtime/config.py'
    text = config.read_text(encoding='utf-8')
    replacements = {
        '    if template:\n        append(f"所选模板说明（{template[\'template_key\']}）", template[\'_documents\'])': '',
        "+ '\\n先读取该DOCX全文及结构，另存工作稿；不要修改参考副本。'": "+ '\\n另存工作稿，不要修改参考副本。'",
        'setting_sources=[] if restricted_tools else ["project", "local"]': 'setting_sources=[]',
    }
    for before, after in replacements.items():
        if text.count(before) != 1:
            raise RuntimeError('测试补丁与当前源码不匹配：' + before[:65])
        text = text.replace(before, after)
    start, end = text.index('DATABASE_APPEND = ('), text.index('USER_FACING_APPEND = (')
    text = text[:start] + 'DATABASE_APPEND = "可使用data工具查询本轮获准数据来源及其结构、定义和语义。"\n' + text[end:]
    config.write_text(text, encoding='utf-8')
    template = next(p for p in (workflow / 'templates/szpt-midterm').glob('*.docx') if not p.name.startswith('~$'))
    manifest = {
        'variant': variant, 'baseCommit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
        'question': QUESTION, 'workflowPrompt': instructions, 'workflowPromptChars': len(instructions),
        'templateSha256': hashlib.sha256(template.read_bytes()).hexdigest(),
        'changes': ['minimal workflow instructions', 'omit template guide injection', 'remove read-full-document instruction',
                    'data discovery without prescribed order', 'disable project/local settings discovery'],
    }
    save(output / 'manifest.json', manifest)
    return repo


async def evaluate(args, output, repo):
    sys.path.insert(0, str(repo / 'python'))
    from runtime.config import load_runtime_environment, prepare_workflow_assets, build_system_prompt
    from runtime.auth import encode_hs256_jwt
    load_runtime_environment('writing-docx')
    os.environ['CCSDK_DATABASES_FILE'] = str(repo / 'config/databases.json')
    policy = json.loads((repo / 'config/databases.json').read_text(encoding='utf-8'))['sources']['schoolDoubleHigh']['policy']
    if policy['project_scope']['mode'] != 'all_school':
        raise RuntimeError('测试要求正式配置已有全校范围，不自动扩大授权')
    payload = {'workflow_name': 'writing-docx', 'capability_ref': 'document-writing', '_template_key': 'szpt-midterm'}
    assets = prepare_workflow_assets(payload)
    prompt = build_system_prompt(database_enabled=True, workflow_config=assets['config'], prompt_documents=assets['prompt'])
    (output / 'system-append.txt').write_text(prompt['append'], encoding='utf-8')
    body = {'protocol': 'agent-run/v1', 'runId': 'eval-' + uuid.uuid4().hex,
            'messageId': 'msg-' + uuid.uuid4().hex, 'businessSessionId': 'eval-' + uuid.uuid4().hex,
            'capabilityRef': 'document-writing', 'payload': {'templateKey': 'szpt-midterm'}, 'input': {'text': QUESTION}}
    save(output / 'request.json', body)
    save(output / 'environment.json', {'model': os.getenv('ANTHROPIC_MODEL'), 'systemAppendChars': len(prompt['append']),
                                     'minutes': args.minutes, 'scope': policy['project_scope']['mode']})
    if args.prepare_only:
        return
    def headers(scope):
        now = int(time.time())
        claims = {'iss': os.getenv('CCSDK_RUNTIME_JWT_ISSUER', 'string-ai-center-service'),
                  'aud': os.getenv('CCSDK_RUNTIME_JWT_AUDIENCE', 'ccsdk-runtime'), 'iat': now,
                  'exp': now + 10800, 'jti': uuid.uuid4().hex, 'scope': scope, 'tenant': policy['tenant_id'],
                  'sub': 'local-user' if policy['users'] == 'all_authenticated' else policy['users'][0],
                  **{k: body[k] for k in ('runId', 'messageId', 'businessSessionId', 'capabilityRef')}}
        return {'Authorization': 'Bearer ' + encode_hs256_jwt(claims, os.environ['CCSDK_RUNTIME_JWT_SECRET'])}
    process = subprocess.Popen([sys.executable, '-c', 'import sys;sys.path.insert(0,"python");import server,uvicorn;'
                                f'uvicorn.run(server.app,host="127.0.0.1",port={args.port},log_level="error")'],
                               cwd=repo, stdout=(output / 'server.log').open('w', encoding='utf-8'), stderr=subprocess.STDOUT)
    save(output / 'process.json', {'serverPid': process.pid, 'port': args.port})
    try:
        async with httpx.AsyncClient(base_url=f'http://127.0.0.1:{args.port}', timeout=60) as client:
            for _ in range(60):
                try:
                    if (await client.get('/health')).status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                await asyncio.sleep(.5)
            else:
                raise RuntimeError('测试服务未就绪')
            route = '/internal/v1/runs/' + body['runId']
            started = time.monotonic()
            response = await client.post('/internal/v1/runs', json=body, headers=headers('run.execute'))
            response.raise_for_status()
            (output / 'run-id.txt').write_text(body['runId'], encoding='utf-8')
            print(json.dumps({'started': args.variant, 'model': os.getenv('ANTHROPIC_MODEL'), 'run': body['runId']}, ensure_ascii=False), flush=True)
            async def collect():
                async with client.stream('GET', route + '/events', headers=headers('run.read'), timeout=None) as stream:
                    stream.raise_for_status()
                    with (output / 'events.jsonl').open('w', encoding='utf-8') as log:
                        async for line in stream.aiter_lines():
                            if line.startswith('data: '):
                                event = json.loads(line[6:]); log.write(json.dumps(event, ensure_ascii=False) + '\n'); log.flush()
                                if event['type'] in ('run.failed', 'run.completed', 'run.cancelled'):
                                    print(event['type'], flush=True)
            collector = asyncio.create_task(collect())
            timed_out = False
            try:
                await asyncio.wait_for(asyncio.shield(collector), args.minutes * 60)
            except asyncio.TimeoutError:
                timed_out = True
                cancel = await client.post(route + '/cancel', headers=headers('run.cancel'))
                save(output / 'cancel.json', {'httpStatus': cancel.status_code, 'response': cancel.text})
                try:
                    await asyncio.wait_for(collector, 30)
                except asyncio.TimeoutError:
                    collector.cancel()
            state = (await client.get(route, headers=headers('run.read'))).json()
            artifacts = (await client.get(route + '/artifacts', headers=headers('run.read'))).json()
            result = {'variant': args.variant, 'elapsedSeconds': round(time.monotonic() - started, 2),
                      'timedOut': timed_out, 'state': state, 'artifacts': artifacts}
            save(output / 'result.json', result)
            for item in artifacts.get('files', []):
                if Path(item['name']).name != item['name']:
                    continue
                download = await client.get(route + '/artifacts/' + item['artifactId'] + '/content', headers=headers('run.read'))
                if download.status_code == 200:
                    (output / item['name']).write_bytes(download.content)
            print(json.dumps({'variant': args.variant, 'elapsed': result['elapsedSeconds'], 'state': state}, ensure_ascii=False), flush=True)
    finally:
        # 仅终止本次隔离服务的进程树，避免取消失效时留下生成进程。
        if process.poll() is None:
            if os.name == 'nt':
                subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            else:
                process.terminate()
            process.wait(timeout=15)
        (repo / '.env').unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('variant', choices=['A', 'B'])
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--port', type=int, default=4321)
    parser.add_argument('--minutes', type=float, default=45)
    parser.add_argument('--prepare-only', action='store_true')
    args = parser.parse_args()
    output = args.output.resolve()
    repo = prepare(output, args.variant)
    asyncio.run(evaluate(args, output, repo))


if __name__ == '__main__':
    main()
