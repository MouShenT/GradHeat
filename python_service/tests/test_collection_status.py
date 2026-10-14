import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from gradheat_python.collection_status import inspect, ProgressTracker
from gradheat_core.intelligence import digest


class CollectionStatusTests(unittest.TestCase):
    def prepare(self, root):
        folder=root/'.research/queue';folder.mkdir(parents=True)
        batch={'schema_version':1,'as_of':'2026-10-15','social':[{'platform':'bili','query':'甲校 考研'}]}
        plan={'schema_version':1,'batches':[batch]}
        (folder/'queue.json').write_text(json.dumps(plan))
        (folder/'runtime.json').write_text(json.dumps({'pid':123,'queue_sha':digest(plan),'state':'collecting-search','processed_batches':1,'current_batch':None}))
        child=folder/f'batch-0000-{digest(batch)[:12]}';child.mkdir()
        (child/'input.json').write_text(json.dumps(batch))
        (child/'report.json').write_text(json.dumps({'receipts':[{'type':'social','platform':'bili','snapshots':3,'database_state':'committed','cookie':'do-not-export'}, {'type':'social','platform':'xhs','snapshots':8,'database_state':'pending'}]}))
        (folder/'search').mkdir()
        (folder/'search/report.json').write_text(json.dumps({'queried_keywords':['甲校考研'],'signals':[{'cookie':'do-not-export'}]}))
        return folder

    def test_collected_signals_are_not_claimed_imported_and_pending_rows_are_not_committed(self):
        with tempfile.TemporaryDirectory() as name:
            root=Path(name);folder=self.prepare(root)
            result=inspect(root,folder,alive=lambda pid:True)
            self.assertEqual(result['discussion_observations_committed'],3)
            self.assertFalse(result['search']['import_completed'])
            self.assertNotIn('cookie',json.dumps(result));self.assertNotIn('do-not-export',json.dumps(result))

    def test_changed_frozen_identity_and_external_paths_are_rejected(self):
        with tempfile.TemporaryDirectory() as name:
            root=Path(name);folder=self.prepare(root)
            (folder/'queue.json').write_text(json.dumps({'schema_version':1,'batches':[{}]}))
            self.assertEqual(inspect(root,folder)['state'],'identity-mismatch')
            with self.assertRaises(ValueError):inspect(root,root.parent)

    def test_lost_owner_is_reported_without_restarting_anything(self):
        with tempfile.TemporaryDirectory() as name:
            root=Path(name);folder=self.prepare(root)
            self.assertEqual(inspect(root,folder,alive=lambda pid:False)['fault'],'owner-exited')
            self.assertIsNone(inspect(root,folder,alive=lambda pid:None)['fault'])

    def test_stall_uses_actual_progress_and_torn_receipt_retains_last_good(self):
        tracker=ProgressTracker(stall_seconds=90)
        snapshot={'receipt_readable':True,'state':'collecting-search','owner_alive':True,'search':{'queried':10}}
        self.assertIsNone(tracker.observe(snapshot,0)['fault'])
        self.assertEqual(tracker.observe(snapshot,91)['fault'],'no-new-receipt')
        snapshot['search']={'queried':11}
        self.assertIsNone(tracker.observe(snapshot,92)['fault'])
        result=tracker.observe({'receipt_readable':False,'state':'receipt-unavailable'},93)
        self.assertEqual(result['last_good_progress']['search']['queried'],11)
        self.assertIsNone(result['fault'])
        self.assertEqual(tracker.observe({'receipt_readable':False,'state':'receipt-unavailable'},184)['fault'],'receipt-unreadable')


if __name__=='__main__':unittest.main()
