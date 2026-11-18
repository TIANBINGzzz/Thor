"""OfficeCLI 只统一模型可见说明，原生命令、Schema 和错误保持不变。"""

import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class OfficeMCPTests(unittest.TestCase):
    def test_only_office_descriptions_change_and_schema_constraints_survive(self):
        from tools.office_mcp import describe_tools

        message = {'jsonrpc': '2.0', 'id': 2, 'result': {'tools': [
            {'name': 'officecli', 'description': 'FIRST load_skill word', 'inputSchema': {
                'type': 'object', 'properties': {'command': {'type': ['string', 'array'],
                    'items': {'type': 'string'}, 'description': 'Run help first'}}, 'required': ['command']}},
            {'name': 'other', 'description': 'Other tool', 'inputSchema': {'type': 'object'}}]}}
        original = copy.deepcopy(message)
        result = describe_tools(message, '统一说明')
        office = result['result']['tools'][0]
        self.assertEqual(office['description'], '统一说明')
        self.assertNotIn('help first', office['inputSchema']['properties']['command']['description'])
        self.assertEqual(office['inputSchema']['properties']['command']['type'], ['string', 'array'])
        self.assertEqual(office['inputSchema']['required'], ['command'])
        self.assertEqual(result['result']['tools'][1], original['result']['tools'][1])
        self.assertEqual(message, original)

    def test_stdio_forwards_native_calls_errors_and_closes_on_eof(self):
        proxy = Path(__file__).resolve().parents[1] / 'tools/office_mcp.py'
        with tempfile.TemporaryDirectory() as directory:
            fake = Path(directory) / 'native.py'
            fake.write_text('''import json, sys
for line in sys.stdin:
    request=json.loads(line)
    if 'id' not in request: continue
    if request['method']=='tools/list':
        result={'tools':[{'name':'officecli','description':'FIRST load_skill word',
                         'inputSchema':{'type':'object','properties':{'command':{'type':'array','items':{'type':'string'},'description':'Run help first'}},'required':['command']}}]}
    else:
        result={'isError':True,'content':[{'type':'text','text':json.dumps(request['params'])}]}
    print(json.dumps({'jsonrpc':'2.0','id':request['id'],'result':result}),flush=True)
''', encoding='utf-8')
            params = {'name': 'officecli', 'arguments': {'command': ['batch', '稿件.docx', '--commands', '[{"command":"view","mode":"text"}]']}}
            inputs = [{'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list'},
                      {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/call', 'params': params}]
            result = subprocess.run([sys.executable, str(proxy), '--', sys.executable, '-X', 'utf8', str(fake)],
                input=''.join(json.dumps(item, ensure_ascii=False)+'\n' for item in inputs),
                text=True, encoding='utf-8', capture_output=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr)
            outputs = [json.loads(line) for line in result.stdout.splitlines()]
            self.assertEqual(len(outputs), 2)
            self.assertNotIn('FIRST load_skill', outputs[0]['result']['tools'][0]['description'])
            self.assertTrue(outputs[1]['result']['isError'])
            self.assertEqual(json.loads(outputs[1]['result']['content'][0]['text']), params)


if __name__ == '__main__':
    unittest.main()
