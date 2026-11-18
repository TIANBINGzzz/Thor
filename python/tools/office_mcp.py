"""只统一 OfficeCLI 的工具说明；命令、校验与文档编辑仍由原生 MCP 执行。"""

import copy
import json
from pathlib import Path
import subprocess
import sys
import threading


def describe_tools(message, description):
    """保留动态发现的原生 Schema，仅替换与本轮工具指引冲突的说明。"""
    result = copy.deepcopy(message)
    for tool in result.get('result', {}).get('tools', []):
        if tool.get('name') != 'officecli':
            continue
        tool['description'] = description
        command = tool.get('inputSchema', {}).get('properties', {}).get('command')
        if isinstance(command, dict):
            command['description'] = 'OfficeCLI 参数数组；包含空格的参数保持为一个数组元素。'
    return result


def provide_tool(definition, context):
    """用当前解释器启动元数据转发进程，原生连接配置仍由启动 YAML 解析。"""
    connection = context['mcp_connections'][definition.ref]
    return definition.ref, {**connection, 'command': sys.executable,
        'args': [str(Path(__file__).resolve()), '--', connection['command'], *connection.get('args', [])]}


def main(command):
    """逐行转发 JSON-RPC；不重试或重放调用，父连接关闭即关闭原生输入。"""
    manifest = Path(__file__).resolve().parents[2] / '.claude/tools/office/tool.json'
    description = json.loads(manifest.read_text(encoding='utf-8'))['description']
    pending_lists = set()
    process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE)

    def forward_input():
        try:
            for line in sys.stdin.buffer:
                request = json.loads(line)
                if request.get('method') == 'tools/list' and 'id' in request:
                    pending_lists.add(request['id'])
                process.stdin.write(line)
                process.stdin.flush()
        except (BrokenPipeError, OSError):
            pass  # 上游退出后由主线程转发退出状态，不重启有副作用的调用。
        finally:
            process.stdin.close()

    threading.Thread(target=forward_input, daemon=True).start()
    try:
        for line in process.stdout:
            message = json.loads(line)
            if message.get('id') in pending_lists:
                pending_lists.discard(message['id'])
                line = (json.dumps(describe_tools(message, description), ensure_ascii=False)+'\n').encode('utf-8')
            sys.stdout.buffer.write(line)
            sys.stdout.buffer.flush()
        return process.wait()
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


if __name__ == '__main__':
    if len(sys.argv) < 3 or sys.argv[1] != '--':
        raise SystemExit('OfficeCLI MCP command required')
    raise SystemExit(main(sys.argv[2:]))
