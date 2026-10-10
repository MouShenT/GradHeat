"""Frozen sample completeness must survive database recovery without browser requests."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools/research'))
import collect_social_sources as collection
import run_full_social_collection as full
from social_evidence import digest, encode


class SocialRecoveryTests(unittest.TestCase):
    def make_batch(self, root, *, jobs=None, media=None, snapshots=True):
        folder = root / '.research/social/runs/test-run'
        folder.mkdir(parents=True)
        original = folder / 'original.json'
        original.write_text(encode(dict(text='2026复试名单')), encoding='utf-8')
        manifest = dict(run_id=folder.name, as_of='2026-10-08', state='partial',
            snapshots=[dict(source_artifact=str(original),
                source_sha256=hashlib.sha256(original.read_bytes()).hexdigest())] if snapshots else [],
            candidates=[], jobs=jobs or [], media=media or [])
        (folder / 'manifest.json').write_text(encode(manifest), encoding='utf-8')
        return folder, manifest

    def save_receipt(self, folder, **changes):
        receipt = dict(run_id=folder.name, folder=str(folder), database_state='committed',
            database=dict(readback='verified'), snapshots=1, failed_jobs=0, media_missing=0,
            state='collected')
        receipt.update(changes)
        (folder / 'storage-status.json').write_text(encode(receipt), encoding='utf-8')

    def test_resume_preserves_partial_jobs_and_unfetched_images_after_commit(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(collection, 'ROOT', Path(temp)):
            folder, manifest = self.make_batch(Path(temp), jobs=[
                dict(state='needs-human', platform='xhs', reason='platform-verification-required'),
                dict(state='down', platform='zhihu', reason='search-service-unavailable')],
                media=[dict(state='budget-deferred'), dict(state='unavailable-at-check')])
            frozen = (folder / 'manifest.json').read_bytes()
            with patch.object(collection, 'ingest', return_value=dict(readback='verified')) as ingest:
                result = collection.resume(folder)
            ingest.assert_called_once_with(manifest, folder)
            self.assertEqual(result['database_state'], 'committed')
            self.assertEqual(result['sampling_state'], 'partial')
            self.assertFalse(result['sampling_complete'])
            self.assertEqual(result['failed_jobs'], 2)
            self.assertEqual(result['media_missing'], 2)
            self.assertEqual([b['state'] for b in result['blockers']], ['needs-human', 'down'])
            self.assertEqual(result['as_of'], '2026-10-08')
            self.assertEqual((folder / 'manifest.json').read_bytes(), frozen)

    def test_image_only_gap_is_not_erased_by_database_recovery(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(collection, 'ROOT', Path(temp)):
            folder, _ = self.make_batch(Path(temp), jobs=[dict(state='collected')],
                media=[dict(state='budget-deferred')])
            with patch.object(collection, 'ingest', return_value=dict(readback='verified')):
                result = collection.resume(folder)
            self.assertEqual(result['state'], 'partial')
            self.assertEqual(result['failed_jobs'], 0)
            self.assertEqual(result['media_missing'], 1)

    def test_committed_receipt_reuse_is_read_only_and_rebuilds_sampling_state(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(collection, 'ROOT', Path(temp)):
            folder, _ = self.make_batch(Path(temp), jobs=[dict(state='partial', reason='worker-budget-expired')],
                media=[dict(state='budget-deferred')])
            self.save_receipt(folder)
            frozen = {p.name: p.read_bytes() for p in folder.iterdir()}
            with patch.object(collection, 'ingest') as ingest, patch.object(collection, 'persist_result') as publish:
                result = collection.committed_result(folder)
            ingest.assert_not_called()
            publish.assert_not_called()
            self.assertTrue(result['storage_receipt_reused'])
            self.assertEqual((result['failed_jobs'], result['media_missing']), (1, 1))
            self.assertEqual({p.name: p.read_bytes() for p in folder.iterdir()}, frozen)

    def test_unverified_receipt_and_changed_original_cannot_certify_a_commit(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(collection, 'ROOT', Path(temp)):
            folder, _ = self.make_batch(Path(temp))
            self.save_receipt(folder, database={})
            self.assertIsNone(collection.committed_result(folder))
            self.save_receipt(folder, run_id='other-run')
            self.assertIsNone(collection.committed_result(folder))
            (folder / 'storage-status.json').write_text('{', encoding='utf-8')
            self.assertIsNone(collection.committed_result(folder))
            self.save_receipt(folder)
            (folder / 'original.json').write_text('{}', encoding='utf-8')
            with self.assertRaises(ValueError):collection.committed_result(folder)

    def test_parent_distinguishes_human_pause_partial_collection_storage_failure_and_empty(self):
        job = dict(id='one', platform='xhs', as_of='2026-10-08')
        result = dict(database_state='committed', folder='test')
        for state in ('partial', 'down', 'unavailable-at-check', 'unexpected-state'):
            row = full.checkpoint_result(job, result, dict(jobs=[dict(state=state)], snapshots=[]))
            self.assertEqual(row['state'], 'partial')
            self.assertEqual(row['failed_jobs'], 1)
        human = dict(jobs=[dict(state='needs-human')], snapshots=[])
        self.assertEqual(full.checkpoint_result(job, result, human)['state'], 'needs-human')
        self.assertEqual(full.checkpoint_result(job, dict(result, database_state='needs-retry'), human)['state'], 'needs-retry')
        missing_image = dict(jobs=[dict(state='collected')], snapshots=[{}], media=[dict(state='budget-deferred')])
        self.assertEqual(full.checkpoint_result(job, result, missing_image)['state'], 'partial')
        empty = dict(jobs=[dict(state='empty-sample'), dict(state='empty', route='web-discovery')], snapshots=[])
        self.assertEqual(full.checkpoint_result(job, result, empty)['state'], 'empty-sample')
        done = dict(jobs=[dict(state='collected')], snapshots=[{}])
        self.assertEqual(full.checkpoint_result(job, result, done)['state'], 'committed')

    def test_summary_does_not_count_legacy_committed_partial_materials_as_complete(self):
        plan = dict(as_of='2026-10-08', units=['A'], jobs=[dict(id='one')])
        for missing in (dict(media_missing=1), dict(failed_jobs=1), dict(sampling_complete=False)):
            report = full.summary(plan, {'one': dict(state='committed', **missing)})
            self.assertEqual(report['available_jobs_complete'], 0)
            self.assertFalse(report['available_materials_complete'])
            self.assertFalse(report['all_information_verified'])

    def setup_queue(self, root, folder):
        job = dict(unit='A', platform='xhs', keyword='A', as_of='2026-10-08')
        job['id'] = digest(job)
        queue = root / '.research/full-test'
        queue.mkdir(parents=True)
        (queue / 'plan.json').write_text(encode(dict(as_of='2026-10-08', units=['A'], jobs=[job], limit=2)), encoding='utf-8')
        (queue / 'state.json').write_text(encode({job['id']: dict(job, state='needs-retry', folder=str(folder))}), encoding='utf-8')
        return queue, job

    def test_paused_platform_can_reconcile_prior_commit_without_using_browser(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(collection, 'ROOT', Path(temp)), \
                patch.object(full, 'ROOT', Path(temp)), patch.object(full.time, 'sleep'):
            root = Path(temp)
            folder, _ = self.make_batch(root, jobs=[dict(state='partial', reason='worker-budget-expired')])
            self.save_receipt(folder)
            frozen = (folder / 'storage-status.json').read_bytes()
            queue, job = self.setup_queue(root, folder)
            collection.set_platform_health('xhs', 'needs-human', 'platform-verification-required')
            handoff = root / '.research/social/human-browser-handoff.json'
            handoff.write_text('{}', encoding='utf-8')
            with patch.object(full, 'run') as browser, patch.object(full, 'resume') as resume:
                full.execute(queue)
            browser.assert_not_called()
            resume.assert_not_called()
            row = json.loads((queue / 'state.json').read_text(encoding='utf-8'))[job['id']]
            self.assertEqual(row['state'], 'partial')
            self.assertTrue(row['storage_receipt_reused'])
            self.assertEqual((folder / 'storage-status.json').read_bytes(), frozen)
            self.assertTrue(handoff.exists())
            self.assertEqual(collection.platform_health()['xhs']['state'], 'needs-human')

    def test_missing_frozen_batch_remains_retry_and_never_becomes_a_new_query(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(collection, 'ROOT', Path(temp)), \
                patch.object(full, 'ROOT', Path(temp)), patch.object(full.time, 'sleep'):
            root = Path(temp)
            folder = root / '.research/social/runs/missing-run'
            queue, job = self.setup_queue(root, folder)
            with patch.object(full, 'run') as browser:
                full.execute(queue)
                full.execute(queue)
            browser.assert_not_called()
            row = json.loads((queue / 'state.json').read_text(encoding='utf-8'))[job['id']]
            self.assertEqual(row['state'], 'needs-retry')
            self.assertEqual(row['folder'], str(folder))

    def test_running_checkpoint_keeps_frozen_batch_for_recovery_after_interruption(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(collection, 'ROOT', Path(temp)), \
                patch.object(full, 'ROOT', Path(temp)), patch.object(full.time, 'sleep'):
            root = Path(temp)
            folder, _ = self.make_batch(root)
            queue, job = self.setup_queue(root, folder)
            def fail_after_running_checkpoint(path):
                row = json.loads((queue / 'state.json').read_text(encoding='utf-8'))[job['id']]
                self.assertEqual(row['state'], 'running')
                self.assertEqual(row['folder'], str(folder))
                raise TimeoutError('simulated interrupted recovery')
            with patch.object(full, 'run') as browser, patch.object(full, 'committed_result', side_effect=fail_after_running_checkpoint):
                full.execute(queue)
            browser.assert_not_called()
            row = json.loads((queue / 'state.json').read_text(encoding='utf-8'))[job['id']]
            self.assertEqual(row['folder'], str(folder))


if __name__ == '__main__':unittest.main()
