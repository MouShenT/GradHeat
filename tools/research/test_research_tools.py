import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
import requests

ROOT = Path(__file__).resolve().parents[2]

def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

mcp = load('mcp_check', ROOT / 'tools/research/mcp_check.py')
search = load('gradheat_search', ROOT / 'infra/search/gradheat_search.py')

class ResearchChecks(unittest.TestCase):
    def test_sse_chinese_and_notification(self):
        response = requests.Response()
        response.status_code = 200
        response.headers['Content-Type'] = 'text/event-stream'
        response.encoding = 'latin-1'
        response._content = ('data: {"method":"notice"}\n\n' +
            'data: ' + json.dumps({'id': 3, 'result': '研究生招生'}, ensure_ascii=False) + '\n\n').encode()
        session = Mock()
        session.post.return_value = response
        self.assertEqual(mcp.rpc(session, 'https://example.org', {'id': 3})['result'], '研究生招生')

    def run_search(self, directory, data):
        response = Mock()
        response.read.return_value = json.dumps(data).encode()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        opener = Mock()
        opener.open.return_value = response
        with patch.object(search.urllib.request, 'build_opener', return_value=opener):
            return search.search('admissions', ['bing'], Path(directory))

    def test_failed_empty_is_down(self):
        with tempfile.TemporaryDirectory() as directory:
            result = self.run_search(directory, {'results': [], 'unresponsive_engines': [['bing', 'timeout']]})
            self.assertEqual(result['status'], 'down')
            self.assertTrue(Path(result['evidence_record']).exists())

    def test_clean_empty_is_empty(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(self.run_search(directory, {'results': []})['status'], 'empty')

    def test_partial_failure_and_immutable_raw(self):
        with tempfile.TemporaryDirectory() as directory:
            data = {'results': [{'url': 'https://example.org'}], 'unresponsive_engines': [['bing', 'timeout']]}
            first = self.run_search(directory, data)
            second = self.run_search(directory, data)
            self.assertEqual(first['status'], 'degraded')
            self.assertEqual(first['raw_sha256'], second['raw_sha256'])
            self.assertNotEqual(first['evidence_record'], second['evidence_record'])
            self.assertEqual(len(list(Path(directory).glob('*.json'))), 3)

    def test_transport_failure_is_not_zero_observation(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(search.urllib.request, 'build_opener', side_effect=TimeoutError):
                result = search.search('admissions', ['bing'], Path(directory))
            self.assertEqual(result['status'], 'down')
            self.assertIsNone(result['result_count'])

if __name__ == '__main__':
    unittest.main()
