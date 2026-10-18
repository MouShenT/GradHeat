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
    def test_stop_and_missing_browser_leave_unrequested_batch_intact(self):
        for reason in ('stop-requested','browser-unavailable'):
            with self.subTest(reason=reason),tempfile.TemporaryDirectory() as directory:
                root=Path(directory);folder=root/'.research/queue';stop=root/'stop'
                (root/'contracts').mkdir();(root/'contracts/social-collection.json').write_text('{"cdp_port":9222}')
                if reason=='stop-requested':stop.touch()
                with patch.object(queue,'ROOT',root),patch('mediacrawler_worker.cdp_health',return_value=False),patch.object(queue.subprocess,'run') as run:
                    result=queue.execute(self.plan(),folder,stop_file=stop,require_cdp=True)
                    self.assertEqual(result['reason'],reason);self.assertIsNone(result['current_batch']);run.assert_not_called()
                    self.assertFalse(list(folder.glob('batch-*')))

    def test_reconcile_requires_dead_owner_and_verified_recovery(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);folder=root/'.research/queue';folder.mkdir(parents=True)
            plan=self.plan();batch=plan['batches'][0];output=folder/f'batch-0000-{queue.digest(batch)[:12]}';output.mkdir()
            (folder/'queue.json').write_text(queue.canonical(plan),encoding='utf-8')
            (folder/'runtime.json').write_text(json.dumps(dict(pid=99,current_batch=0,state='needs-review')))
            (output/'input.json').write_text(json.dumps(batch),encoding='utf-8')
            report=dict(source_sha=queue.digest(batch),recovered_without_requests=True,receipts=[dict(database_state='committed')],
                retrieval_states={queue.digest(batch['social'][0]):dict(state='needs-review',recovery='no-refetch')})
            (output/'report.json').write_text(json.dumps(report))
            with patch.object(queue,'ROOT',root),patch.object(queue,'process_alive',return_value=True):
                with self.assertRaises(RuntimeError):queue.reconcile_recovered(folder)
            with patch.object(queue,'ROOT',root),patch.object(queue,'process_alive',return_value=False):
                result=queue.reconcile_recovered(folder)
                self.assertEqual(result['processed_batches'],1);self.assertIsNone(result['current_batch'])
            self.assertTrue((folder/'checkpoint-before-recovery-0000.json').exists())

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

    def test_followup_waits_for_owner_exit_and_verified_terminal_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);folder=root/'.research/next';old=root/'.research/old'
            states=[dict(receipt_readable=True,state='collecting',owner_alive=True),
                dict(receipt_readable=True,state='budget-ended',owner_alive=False)]
            with patch.object(queue,'ROOT',root),patch.object(queue,'inspect',side_effect=states),patch.object(queue.time,'sleep') as sleep,patch.object(queue,'_execute',return_value={'state':'collecting'}) as execute:
                result=queue.execute_after(self.plan(),folder,old)
                sleep.assert_called_once_with(15);execute.assert_called_once()
                self.assertEqual(result['state'],'collecting')

    def test_followup_preserves_uncertain_upstream_without_collecting(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);folder=root/'.research/next'
            with patch.object(queue,'ROOT',root),patch.object(queue,'inspect',return_value=dict(receipt_readable=True,state='collecting',owner_alive=False,fault='owner-exited')),patch.object(queue,'_execute') as execute:
                self.assertEqual(queue.execute_after(self.plan(),folder,root/'.research/old')['reason'],'upstream-needs-review')
                execute.assert_not_called()

    def test_followup_does_not_clear_its_own_interrupted_batch(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);folder=root/'.research/next';folder.mkdir(parents=True)
            (folder/'runtime.json').write_text(json.dumps({'current_batch':0,'state':'collecting'}))
            with patch.object(queue,'ROOT',root),patch.object(queue,'inspect') as inspect,patch.object(queue.subprocess,'run') as run:
                self.assertEqual(queue.execute_after(self.plan(),folder,root/'.research/old')['reason'],'interrupted-batch-checkpoint')
                inspect.assert_not_called();run.assert_not_called()


if __name__=='__main__':unittest.main()
