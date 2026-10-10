import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from gradheat_python.api import create_app
from gradheat_python.config import Settings
from gradheat_python.publication import FrozenPublication, PublicationReader, verified
from gradheat.material_store import encode
from fastapi.testclient import TestClient


def payload():
    def programme(n, code, name, group, eligible=True):
        return dict(id=str(n) * 24, unit='合成' + str(n) + '大学', department='计算机学院',
            year=2027, major_code=code, major_name=name, group=group, mode='全日制', degree_type='学术学位',
            eligible_11408=eligible, subjects=['101', '201', '301', '408'] if eligible else ['101', '204', '302', '408'],
            plan_text='专业：100（含推免）', plan_variants=[], ordinary_quota=None, plan_status='待核')
    return dict(data_as_of='2026-10-09', programmes=[programme(1, '081200', '计算机科学与技术', '985'),
        programme(2, '083500', '软件工程', '研究所'), programme(3, '085404', '计算机技术', '其他招生单位', False)],
        history=[], units=[dict(name='合成' + str(n) + '大学') for n in (1, 2, 3)])


class HeatStub:
    def read(self, unit):
        return {'unit': unit, 'read_state': 'no-stored-sample', 'platforms': [], 'applicant_count': None}


class InternalApiTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.root = Path(self.folder.name)
        self.data = payload()
        self.version = hashlib.sha256(encode(self.data).encode()).hexdigest()
        self.settings = Settings(root=self.root, internal_token='synthetic-internal-token-' + 'x' * 32)
        self.auth = {'X-GradHeat-Internal-Token': self.settings.internal_token}
        self.client = TestClient(create_app(self.settings, publications=FrozenPublication(self.data), heat=HeatStub()))

    def tearDown(self):
        self.client.close()
        self.folder.cleanup()

    def test_authentication_and_no_local_research_dependency(self):
        self.assertEqual(self.client.get('/health').status_code, 200)
        self.assertEqual(self.client.get('/internal/v1/dashboard').status_code, 401)
        with patch('gradheat_workbench.repository.ResearchRepository', side_effect=AssertionError('must not read local dossiers')):
            response = self.client.get('/internal/v1/dashboard', headers=self.auth)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['data_version'], self.version)
        self.assertEqual(response.json()['programmes'][0]['background']['friendliness'], 'unknown')
        self.assertEqual(list(self.root.iterdir()), [])
        with self.assertRaises(ValueError):
            create_app(Settings(internal_token=''))

    def test_no_score_recommendation_is_preferences_not_background_prediction(self):
        response = self.client.post('/internal/v1/recommendations', headers=self.auth,
            json={'data_version': self.version, 'majors': ['计算机', '软件'], 'group_weights': {'985': 2, '研究所': 8}})
        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()
        self.assertEqual(result['eligible_candidates'], 2)
        self.assertEqual(result['ranking'][0]['group'], '研究所')
        self.assertTrue(all(row['background']['friendliness'] == 'unknown' for row in result['ranking']))
        self.assertNotIn('admission_probability', result)
        wrong = self.client.post('/internal/v1/recommendations', headers=self.auth,
            json={'data_version': 'f' * 64})
        self.assertEqual(wrong.status_code, 409)
        bad_group = self.client.post('/internal/v1/recommendations', headers=self.auth,
            json={'data_version': self.version, 'group_weights': {'无证据实力A+': 10}})
        self.assertEqual(bad_group.status_code, 422)

    def test_game_is_versioned_and_excludes_non_11408(self):
        value = {'data_version': self.version, 'participants': 30, 'options': [
            {'programme_id': '1' * 24, 'capacity': 10, 'preference': 5},
            {'programme_id': '2' * 24, 'capacity': 20, 'preference': 5}]}
        response = self.client.post('/internal/v1/game-scenario', headers=self.auth, json=value)
        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()
        self.assertEqual(result['data_version'], self.version)
        self.assertTrue(result['base']['converged'])
        self.assertIsNone(result['admission_probability'])
        self.assertLessEqual(result['base']['maximum_improvement'], 1e-9)
        value['options'][1]['programme_id'] = '3' * 24
        self.assertEqual(self.client.post('/internal/v1/game-scenario', headers=self.auth, json=value).status_code, 422)
        value.pop('data_version')
        self.assertEqual(self.client.post('/internal/v1/game-scenario', headers=self.auth, json=value).status_code, 422)

    def test_comparison_exact_archive_compatibility(self):
        request = {'data_version': self.version, 'title': '合成比较', 'weights': {
            'research': 7, 'location': 1, 'cost': 1, 'career': 3, 'training': 2},
            'candidates': [{'programme_id': '1' * 24, 'ratings': {'research': {'low': 4.333333333333, 'high': 9.777777777777}}}, {'programme_id': '2' * 24}]}
        response = self.client.post('/internal/v1/comparisons/evaluate', headers=self.auth, json=request)
        self.assertEqual(response.status_code, 200, response.text)
        packet = response.json()
        self.assertEqual(packet['comparison_id'], hashlib.sha256(packet['canonical_archive'].encode()).hexdigest())
        self.assertEqual(packet['canonical_archive'], encode({'result': packet['result'], 'report_md': packet['report_md']}))
        self.assertEqual(json.loads(packet['canonical_result']), packet['result'])
        self.assertEqual(packet['result_sha256'], hashlib.sha256(packet['canonical_result'].encode()).hexdigest())
        self.assertEqual(packet['canonical_record'], packet['canonical_archive'])

    def test_frozen_publication_requires_hash_and_bad_bytes_are_not_latest(self):
        filename = self.root / 'frozen.json'
        filename.write_text(encode(self.data), encoding='utf-8')
        reader = PublicationReader(None, Settings(root=self.root, publication_file=filename, publication_sha=self.version))
        self.assertEqual(reader.get(), self.data)
        self.assertEqual(reader.get_version(self.version), self.data)
        with self.assertRaises(ValueError):
            reader.get_version('e' * 64)
        filename.write_text(encode(dict(self.data, data_as_of='2026-10-10')), encoding='utf-8')
        with self.assertRaises(ValueError):
            reader.get(force=True)
        with self.assertRaises(ValueError):
            verified('f' * 64, encode(self.data))

    def test_body_budget_even_without_content_length(self):
        response = self.client.post('/internal/v1/recommendations', headers=self.auth, content=b' ' * 200001)
        self.assertEqual(response.status_code, 413)
        self.assertEqual(self.client.get('/internal/v1/heat', headers=self.auth, params={'unit': '不存在'}).status_code, 404)


if __name__ == '__main__':
    unittest.main()
