"""汇总撰写运行的调用、上下文压缩与错误；不把工具成功当成文稿验收。"""

import argparse
from collections import Counter
import json
from pathlib import Path
import re
import shlex


def records(path):
    with path.open(encoding='utf-8') as source:
        for line in source:
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue  # 正在运行的JSONL尾行可能尚未写完。


def audit(folder, trace_dir):
    events = list(records(folder / 'events.jsonl'))
    starts = {e['payload']['toolCallId']: e['occurredAt'] for e in events if e['type'] == 'tool.started'}
    ends = {e['payload']['toolCallId']: e['occurredAt'] for e in events if e['type'] == 'tool.finished'}
    calls, results, compactions = {}, {}, {}
    for trace in trace_dir.rglob('*.jsonl'):
        for entry in records(trace):
            if entry.get('subtype') == 'compact_boundary' and trace.parent == trace_dir:
                meta = entry.get('compactMetadata', {})
                compactions[entry['uuid']] = {k: meta.get(k) for k in ('durationMs', 'preTokens', 'postTokens')}
            blocks = entry.get('message', {}).get('content', [])
            for block in blocks if isinstance(blocks, list) else []:
                if block.get('type') == 'tool_use' and block['id'] in starts:
                    calls[block['id']] = block
                elif block.get('type') == 'tool_result' and block['tool_use_id'] in starts:
                    results[block['tool_use_id']] = block
    tool_counts, returned, supplied = Counter(), Counter(), Counter()
    errors, queries, edits, scripts = [], [], [], []
    for key, call in calls.items():
        name, arguments = call['name'], call['input']
        result = results.get(key, {})
        content = result.get('content', '')
        text = content if isinstance(content, str) else '\n'.join(b.get('text', '') for b in content if b.get('type') == 'text')
        try:
            parsed = json.loads(text)
        except (ValueError, TypeError):
            parsed = {}
        failed = result.get('is_error') or isinstance(parsed, dict) and (parsed.get('status') == 'failed' or parsed.get('isError'))
        if failed:
            errors.append({'tool': name, 'seconds': round((starts[key] - events[0]['occurredAt']) / 1000, 2),
                           'code': (parsed.get('error') or {}).get('code') if isinstance(parsed, dict) else None,
                           'message': text[:350]})
        label = name
        if name == 'mcp__office__officecli':
            command = arguments.get('command', [])
            command = shlex.split(command) if isinstance(command, str) else command
            if command:
                label = 'office:' + command[0]
                if command[0] in ('set', 'batch', 'add', 'remove', 'insert') and result and not failed and 'no changes were applied' not in text:
                    edits.append(starts[key])
        if name in ('mcp__data__execute_query_spec', 'mcp__data__execute_readonly_sql'):
            queries.append(json.dumps([name, arguments], ensure_ascii=False, sort_keys=True))
        if name == 'Write':
            path = arguments.get('file_path', '')
            if Path(path).suffix in ('.py', '.js', '.ps1', '.sh'):
                scripts.append({'file': Path(path).name, 'characters': len(arguments.get('content', ''))})
        tool_counts[label] += 1
        returned[label] += len(text)
        supplied[label] += len(json.dumps(arguments, ensure_ascii=False))
    intervals = sorted((start, ends[key]) for key, start in starts.items() if key in ends)
    total, right = 0, 0
    for left, end in intervals:
        total += max(0, end - max(left, right))
        right = max(right, end)
    summary = {
        'elapsedSeconds': round((events[-1]['occurredAt'] - events[0]['occurredAt']) / 1000, 2),
        'lastEvent': events[-1]['type'], 'toolCalls': len(starts), 'matchedCalls': len(calls),
        'toolActiveSeconds': round(total / 1000, 2),
        'firstSuccessfulOfficeEditSeconds': round((min(edits) - events[0]['occurredAt']) / 1000, 2) if edits else None,
        'tools': dict(tool_counts), 'returnedCharacters': dict(returned), 'inputCharacters': dict(supplied),
        'duplicateDataRequests': len(queries) - len(set(queries)), 'errors': errors,
        'compactions': list(compactions.values()),
        'compactionSeconds': round(sum(x.get('durationMs') or 0 for x in compactions.values()) / 1000, 2),
        'modelWrittenScripts': scripts,
    }
    # Bash也能写出脚本，补充磁盘清单，避免只统计Write调用漏记生成代码。
    summary['workspaceScripts'] = []
    for work in (folder / 'repo/.scribe-runs/client-sessions').glob('*/.work'):
        for path in sorted(work.rglob('*')):
            if path.is_file() and path.suffix in ('.py', '.js', '.ps1', '.sh') and 'references' not in path.relative_to(work).parts:
                content = path.read_text(encoding='utf-8', errors='replace')
                summary['workspaceScripts'].append({'file': path.relative_to(work).as_posix(),
                                                    'characters': len(content), 'lines': len(content.splitlines())})
    (folder / 'metrics.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run_directory', type=Path)
    parser.add_argument('--trace-directory', type=Path)
    args = parser.parse_args()
    folder = args.run_directory.resolve()
    trace = args.trace_directory or Path.home() / '.claude/projects' / re.sub(r'[^A-Za-z0-9]', '-', str(folder / 'repo'))
    result = audit(folder, trace)
    print(json.dumps({k: v for k, v in result.items() if k not in ('errors', 'returnedCharacters', 'inputCharacters', 'compactions')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
