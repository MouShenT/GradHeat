import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools/research'))
import run_collection_queue as queue


class QueueTests(unittest.TestCase):
    def plan(self):
        return {'schema_version':1,'batches':[{'schema_version':1,'as_of':'2026-10-15',
            'social':[{'platform':'bili','query':'甲校 计算机考研','limit':20}], 'websites':[]}]}

    def test_interrupted_receipt_is_preserved_without_resending(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);folder=root/'.research/queue';folder.mkdir(parents=True)
            (folder/'runtime.json').write_text(json.dumps({'current_batch':0,'state':'collecting'}))
            with patch.object(queue,'ROOT',root),patch.object(queue.subprocess,'run') as run:
                result=queue.execute(self.plan(),folder)
                self.assertEqual(result['state'],'needs-review');run.assert_not_called()

    def test_frozen_completed_batch_is_not_refetched_and_changed_input_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);folder=root/'.research/queue';plan=self.plan();batch=plan['batches'][0]
            output=folder/f'batch-0000-{queue.digest(batch)[:12]}';output.mkdir(parents=True)
            (output/'input.json').write_text(queue.canonical(batch),encoding='utf-8')
            (output/'report.json').write_text('{}')
            with patch.object(queue,'ROOT',root),patch.object(queue.subprocess,'run') as run:
                self.assertEqual(queue.execute(plan,folder)['state'],'queue-processed');run.assert_not_called()
                changed=self.plan();changed['batches'][0]['social'][0]['query']='乙校 计算机考研'
                with self.assertRaises(ValueError):queue.execute(changed,folder)
                run.assert_not_called()

    def test_next_batch_waits_for_existing_collector_and_failure_keeps_checkpoint(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);folder=root/'.research/queue'
            with patch.object(queue,'ROOT',root),patch.object(queue.subprocess,'run',return_value=Mock(returncode=1)) as run:
                result=queue.execute(self.plan(),folder)
                self.assertEqual(result['state'],'needs-review');self.assertEqual(result['current_batch'],0)
                self.assertIn('--wait-for-lock',run.call_args.args[0])


if __name__=='__main__':unittest.main()
