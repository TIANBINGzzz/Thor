"""Keep the published API page aligned with executable request contracts."""

from html.parser import HTMLParser
import json
from pathlib import Path
import re
import unittest

import server
from runtime.protocol import AgentRunRequest
from runtime.event_display import with_display_name


class ReferenceParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.text = []
        self.examples = []
        self.current = None

    def handle_starttag(self, tag, attrs):
        if tag == 'pre':
            self.current = []

    def handle_data(self, data):
        self.text.append(data)
        if self.current is not None:
            self.current.append(data)

    def handle_endtag(self, tag):
        if tag == 'pre' and self.current is not None:
            self.examples.append(''.join(self.current))
            self.current = None


@unittest.skipUnless((Path(__file__).resolve().parents[2] / 'doc/python-api.html').is_file(),
                     'API 文档仅在完整开发仓库校验，不随发布源码或镜像交付')
class APIReferenceTests(unittest.TestCase):
    def setUp(self):
        self.page = ReferenceParser()
        self.page.feed((Path(__file__).resolve().parents[2] / 'doc/python-api.html').read_text(encoding='utf-8'))

    def test_all_runtime_routes_are_documented(self):
        text = re.sub(r'\{[^}]+\}', '{}', '\n'.join(self.page.text))
        for route in server.app.routes:
            with self.subTest(path=route.path):
                self.assertTrue(re.sub(r'\{[^}]+\}', '{}', route.path) in text,
                                f'Undocumented route: {route.path}')

    def test_full_run_request_examples_follow_current_protocol(self):
        count = 0
        for example in self.page.examples:
            if not example.lstrip().startswith('{'):
                continue
            data = json.loads(example)
            if data.get('protocol') == 'agent-run/v1':
                AgentRunRequest.from_dict(data)
                count += 1
        self.assertGreater(count, 0)

    def test_capability_response_matches_registered_catalog(self):
        examples = [json.loads(example) for example in self.page.examples
                    if example.lstrip().startswith('{')]
        catalogs = [item['capabilities'] for item in examples if 'capabilities' in item]
        self.assertEqual(catalogs, [[item.to_public_dict() for item in server.CAPABILITIES.values()]])

    def test_event_examples_use_the_python_display_dictionary(self):
        events = [json.loads(example) for example in self.page.examples
                  if example.lstrip().startswith('{')]
        events = [event for event in events if event.get('protocolVersion') == 'agent-events/v1']
        self.assertTrue(events)
        for event in events:
            with self.subTest(type=event['type']):
                self.assertEqual(event, with_display_name(event))
