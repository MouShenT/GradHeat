import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from gradheat_workbench.field_lineage import load_overrides, resolve, load_exclusions, excluded
from gradheat_workbench.corroboration import canonical, Corroborator, scope, digest, observations


class FieldLineageTests(unittest.TestCase):
    def setup_review(self, root):
        original = root / 'original.json'
        original.write_text('{"note":"plan2026按学校目录转载改为7"}', encoding='utf-8')
        entry = dict(candidate_id='candidate-a', field='plan_text', artifact=str(original),
            artifact_sha256=hashlib.sha256(original.read_bytes()).hexdigest(), locator='units[0]',
            origin_id='school-directory-chain', source_url='https://example.org/catalogue',
            reason='This plan is explicitly attributed to the same school directory',
            quote_field='note', quote='plan2026按学校目录转载改为7', expected_value='7',
            reviewed_at='2026-10-09T05:00:00Z', verification='passage-verified')
        sidecar = root / '.research/source-consensus/field-origin-overrides.json'
        sidecar.parent.mkdir(parents=True)
        sidecar.write_text(json.dumps([entry], ensure_ascii=False), encoding='utf-8')
        row = dict(id=entry['candidate_id'], artifact_sha256=entry['artifact_sha256'],
            locator=entry['locator'], raw={'note': entry['quote']})
        return entry, row, original

    def test_same_upstream_plan_does_not_keep_two_votes_or_change_other_field(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); entry, row, _ = self.setup_review(root)
            overrides = load_overrides(root)
            review = resolve(row, 'plan_text', 7, overrides, canonical)
            self.assertIsNone(resolve(row, 'cutoff_text', 264, overrides, canonical))
            programme = dict(unit='样本大学', year=2026, major_code='085410', major_name='人工智能')
            key = scope(programme, 'programme')
            observations = []
            for provider in ('school-directory-chain', review['origin_id']):
                item = dict(scope=key, scope_id=digest(key), field='plan_text', value='7', raw_value='7', origin_id=provider, official=False)
                item['id'] = digest(item); observations.append(item)
            verdict, _ = Corroborator(observations).decision(programme, 'programme', 'plan_text', '7')
            self.assertEqual(verdict['state'], 'pending')
            self.assertEqual(verdict['agreeing_sources'], 1)

    def test_changed_quote_value_or_original_cannot_apply_old_review(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); _, row, original = self.setup_review(root)
            overrides = load_overrides(root)
            with self.assertRaises(ValueError): resolve(row | {'raw': {'note': 'unrelated'}}, 'plan_text', '7', overrides, canonical)
            with self.assertRaises(ValueError): resolve(row, 'plan_text', '8', overrides, canonical)
            original.write_text('changed original', encoding='utf-8')
            with self.assertRaises(ValueError): load_overrides(root)

    def test_observation_generator_uses_review_for_only_the_reviewed_field(self):
        sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools/research'))
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); entry, row, original = self.setup_review(root)
            row.update(unit='样本大学', year=2026, major_name='人工智能', kind='history',
                scope_status='pending', source_family='noobdream', plan_text='7',
                cutoff_text='264', artifact=str(original))
            candidates = root / '.research/github-sources/candidates.json'
            candidates.parent.mkdir(parents=True)
            candidates.write_text(json.dumps([row], ensure_ascii=False), encoding='utf-8')
            result = observations(SimpleNamespace(root=root, programmes={}, data={}))
            plan = next(r for r in result if r['field'] == 'plan_text')
            line = next(r for r in result if r['field'] == 'cutoff_text')
            self.assertEqual(plan['origin_id'], 'school-directory-chain')
            self.assertEqual(plan['source_url'], entry['source_url'])
            self.assertTrue(plan['lineage_review_sha256'])
            self.assertEqual(line['origin_id'], 'noobdream')
            self.assertNotIn('lineage_review_sha256', line)

    def test_reviewed_mixed_population_is_excluded_but_original_remains(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); entry, row, original = self.setup_review(root)
            review = entry | {'action': 'exclude-row'}
            path = root / '.research/source-consensus/candidate-exclusions.json'
            path.write_text(json.dumps([review], ensure_ascii=False), encoding='utf-8')
            reviews = load_exclusions(root)
            self.assertTrue(excluded(row, '*', reviews))
            self.assertTrue(excluded(row, 'admit_text', reviews))
            self.assertFalse(excluded(row | {'id': 'different-candidate'}, '*', reviews))
            self.assertTrue(original.is_file())

    def test_unclear_lineage_withholds_only_its_field(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); entry, row, _ = self.setup_review(root)
            path = root / '.research/source-consensus/candidate-exclusions.json'
            path.write_text(json.dumps([entry | {'action': 'withhold-field'}], ensure_ascii=False), encoding='utf-8')
            reviews = load_exclusions(root)
            self.assertTrue(excluded(row, 'plan_text', reviews))
            self.assertFalse(excluded(row, 'cutoff_text', reviews))
            self.assertFalse(excluded(row, '*', reviews))


if __name__ == '__main__':
    unittest.main()
