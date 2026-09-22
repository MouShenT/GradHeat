import copy
import json
import unittest
from validate_release import ROOT, SCHEMA, validate, Draft202012Validator

class ReleaseGateTests(unittest.TestCase):
    def setUp(self):
        self.data = json.loads((ROOT / 'contracts/examples/descriptive.json').read_text())

    def test_schema_and_descriptive_fixture(self):
        Draft202012Validator.check_schema(SCHEMA)
        self.assertEqual(validate(self.data), [])

    def test_future_publication_rejected(self):
        self.data['evidence'][0]['published_at'] = '2025-10-02T00:00:00Z'
        self.assertTrue(any('publication after' in e for e in validate(self.data)))

    def test_late_observation_rejected_in_live_mode(self):
        self.data['evidence'][0]['observed_at'] = '2025-10-02T00:00:00Z'
        self.assertTrue(any('live cutoff' in e for e in validate(self.data)))

    def test_reconstruction_requires_proof(self):
        self.data['mode'] = 'reconstructed'
        self.data['evidence'][0]['observed_at'] = '2025-10-02T00:00:00Z'
        self.assertTrue(any('publication_proof' in e for e in validate(self.data)))
        self.data['evidence'][0]['publication_proof'] = 'synthetic-version-history'
        self.assertEqual(validate(self.data), [])

    def test_probability_requires_model_reviews(self):
        self.data['capability'] = 'probability'
        self.assertEqual(len(validate(self.data)), 4)
        for name in ['scenario_sensitivity', 'temporal_validation', 'calibration', 'applicability']:
            self.data['checks'][name] = {'status': 'passed', 'report_ref': 'synthetic-review'}
        self.assertEqual(validate(self.data), [])
        self.data['checks']['calibration']['status'] = 'failed'
        self.assertTrue(any('calibration' in e for e in validate(self.data)))

    def test_duplicate_and_missing_evidence(self):
        self.data['evidence'].append(copy.deepcopy(self.data['evidence'][0]))
        self.assertTrue(any('duplicate' in e for e in validate(self.data)))
        self.data['evidence'] = []
        self.assertTrue(validate(self.data))

    def test_timezone_required(self):
        self.data['cutoff'] = '2025-10-01T00:00:00'
        self.assertTrue(validate(self.data))

    def test_invalid_dates_and_unknown_offsets(self):
        for value in ['2025-02-30T00:00:00Z', '2025-10-01T00:00:00-00:00', '2025-10-01T00:00:00+08:99', 'not-a-date']:
            with self.subTest(value=value):
                self.data['cutoff'] = value
                self.assertTrue(validate(self.data))

    def test_equivalent_timezone_instants(self):
        self.data['evidence'][0]['observed_at'] = '2025-10-01T08:00:00+08:00'
        self.assertEqual(validate(self.data), [])

    def test_source_url_without_host_or_with_credentials(self):
        for value in ['https://', 'https://user:password@example.org/file']:
            self.data['evidence'][0]['source_url'] = value
            self.assertTrue(validate(self.data))

    def test_observation_after_release_rejected(self):
        self.data['evidence'][0]['observed_at'] = '2026-01-01T00:00:00Z'
        self.assertTrue(any('release generation' in e for e in validate(self.data)))

    def test_pending_or_blank_review_blocks_release(self):
        self.data['checks']['pool_consistency']['status'] = 'pending'
        self.assertTrue(validate(self.data))
        self.data['checks']['pool_consistency'] = {'status': 'passed', 'report_ref': '  '}
        self.assertTrue(validate(self.data))

if __name__ == '__main__':
    unittest.main()
