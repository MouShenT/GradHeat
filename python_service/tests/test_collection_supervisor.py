import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'tools/application'))
import collection_supervisor as service


class CollectionSupervisorTests(unittest.TestCase):
    def setup_project(self, root, batches=None):
        folder = root/'.research/collection-service'
        queue = root/'.research/queue'
        folder.mkdir(parents=True)
        queue.mkdir(parents=True)
        (queue/'queue.json').write_text(json.dumps(dict(schema_version=1, batches=batches or [dict(social=[{}], websites=[])])), encoding='utf-8')
        config = folder/'config.json'
        config.write_text(json.dumps(dict(runtime_dir=str(folder), python='synthetic-python', queues=[str(queue)],
                                          budget_hours=8, interval_seconds=15)), encoding='utf-8')
        return folder, queue, config

    def snapshot(self, **changes):
        return dict(dict(receipt_readable=True, owner_alive=False, state='budget-ended',
                         current_batch=None, completed_batches=0, total_batches=1, fault=None), **changes)

    def test_private_frozen_unique_queues_and_explicit_runtime_required(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            folder, queue, config=self.setup_project(root)
            with patch.object(service, 'ROOT', root):
                self.assertEqual(service.load_config(config)['queues'], [queue])
                original=json.loads(config.read_text())
                for values in (dict(original,queues=[str(queue),str(queue)]),
                               dict(original,queues=[str(root/'outside')]), dict(original,python=''),
                               dict(original,budget_hours=True), dict(original,interval_seconds=1)):
                    config.write_text(json.dumps(values), encoding='utf-8')
                    with self.subTest(values=values), self.assertRaises(ValueError):
                        service.load_config(config)

    def test_uncertain_receipt_and_live_owner_never_authorize_restart(self):
        with tempfile.TemporaryDirectory() as temporary:
            queue=Path(temporary)
            self.assertEqual(service.action(queue, {}), 'ready')
            (queue/'runtime.json').write_text('{}')
            self.assertEqual(service.action(queue, self.snapshot()), 'ready')
            for change, expected in ((dict(owner_alive=True),'watching-existing-owner'),
                                     (dict(owner_alive=None),'watching-existing-owner'),
                                     (dict(current_batch=0),'needs-review'),
                                     (dict(state='needs-review'),'needs-review'),
                                     (dict(state='collecting'),'needs-review'),
                                     (dict(receipt_readable=False),'needs-review'),
                                     (dict(state='queue-processed'),'needs-review'),
                                     (dict(state='queue-processed',completed_batches=1),'complete')):
                with self.subTest(change=change):
                    self.assertEqual(service.action(queue,self.snapshot(**change)),expected)

    def test_never_started_upstream_waiter_requires_completed_predecessors(self):
        with tempfile.TemporaryDirectory() as temporary:
            queue=Path(temporary)
            pointer=queue/'runtime.json'
            record=dict(state='needs-review',reason='upstream-needs-review',current_batch=None,processed_batches=0)
            pointer.write_text(json.dumps(record))
            before=pointer.read_bytes()
            snapshot=self.snapshot(state='needs-review')
            self.assertEqual(service.action(queue,snapshot),'needs-review')
            self.assertEqual(service.action(queue,snapshot,preceding_complete=True),'ready')
            self.assertEqual(pointer.read_bytes(),before)
            for changed in (dict(record,reason='interrupted-batch-checkpoint'),dict(record,current_batch=0),
                            dict(record,processed_batches=1),dict(record,processed_batches=False),
                            {k:v for k,v in record.items() if k!='current_batch'}):
                pointer.write_text(json.dumps(changed))
                with self.subTest(changed=changed):
                    self.assertEqual(service.action(queue,snapshot,preceding_complete=True),'needs-review')
            pointer.write_text(json.dumps(record))
            self.assertEqual(service.action(queue,self.snapshot(state='needs-review',owner_alive=True),True),'watching-existing-owner')

    def test_browser_unavailable_waits_without_spending_a_single_task(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            folder, queue, config=self.setup_project(root)
            before=(queue/'queue.json').read_bytes()
            def sleep(_): (folder/'stop').touch()
            with patch.object(service,'ROOT',root), patch.object(service,'inspect',return_value={}), \
                 patch.object(service,'other_collector_alive',return_value=False), \
                 patch.object(service,'browser_available',return_value=False), \
                 patch.object(service.subprocess,'Popen') as launch, patch.object(service.time,'sleep',side_effect=sleep):
                service.run(config)
            launch.assert_not_called()
            self.assertFalse((queue/'runtime.json').exists())
            self.assertEqual((queue/'queue.json').read_bytes(), before)

    def test_browser_probe_requires_a_valid_existing_local_debugger(self):
        for metadata, expected in (([],False), ({},False),
                                   ({'webSocketDebuggerUrl':'ws://remote.example/devtools/browser/1'},False),
                                   ({'webSocketDebuggerUrl':'ws://127.0.0.1:9222/devtools/browser/1'},True)):
            with self.subTest(metadata=metadata):
                response=Mock(status=200)
                response.read.return_value=json.dumps(metadata).encode()
                context=Mock()
                context.__enter__=Mock(return_value=response)
                context.__exit__=Mock(return_value=False)
                opener=Mock()
                opener.open.return_value=context
                with patch.object(service.urllib.request,'build_opener',return_value=opener):
                    self.assertEqual(service.browser_available(9222),expected)
                self.assertEqual(opener.open.call_args.args[0],'http://127.0.0.1:9222/json/version')

    def test_stop_waits_for_owned_batch_without_terminating_it(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            folder, queue, config=self.setup_project(root)
            child=Mock(pid=123, returncode=0)
            child.poll.side_effect=[None,0]
            sleeps=0
            def sleep(_):
                nonlocal sleeps
                sleeps+=1
                (folder/'stop').touch()
            with patch.object(service,'ROOT',root), patch.object(service,'inspect',return_value={}), \
                 patch.object(service,'other_collector_alive',return_value=False), \
                 patch.object(service,'browser_available',return_value=True), \
                 patch.object(service.subprocess,'Popen',return_value=child) as launch, \
                 patch.object(service.time,'sleep',side_effect=sleep):
                service.run(config)
            self.assertEqual(launch.call_count,1)
            command=launch.call_args.args[0]
            self.assertIn('--stop-file',command)
            self.assertIn('--require-cdp',command)
            self.assertEqual(command[command.index('--hours')+1],'8')
            self.assertGreaterEqual(sleeps,2)
            child.terminate.assert_not_called()
            child.kill.assert_not_called()
            child.wait.assert_not_called()
            self.assertEqual(json.loads((folder/'runtime.json').read_text())['state'],'stopped')

    def test_existing_owner_and_uncertain_batch_do_not_spawn_children(self):
        for snapshot in (self.snapshot(owner_alive=True), self.snapshot(current_batch=0)):
            with self.subTest(snapshot=snapshot), tempfile.TemporaryDirectory() as temporary:
                root=Path(temporary)
                folder, queue, config=self.setup_project(root)
                (queue/'runtime.json').write_text('{}')
                def sleep(_): (folder/'stop').touch()
                with patch.object(service,'ROOT',root), patch.object(service,'inspect',return_value=snapshot), \
                     patch.object(service,'other_collector_alive',return_value=False), \
                     patch.object(service.subprocess,'Popen') as launch, patch.object(service.time,'sleep',side_effect=sleep):
                    service.run(config)
                launch.assert_not_called()

    def test_unexpected_child_exit_preserves_receipt_and_does_not_loop_requests(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            folder, queue, config=self.setup_project(root)
            pointer=queue/'runtime.json'
            pointer.write_text('{}')
            child=Mock(pid=123,returncode=1)
            child.poll.return_value=1
            sleeps=0
            def sleep(_):
                nonlocal sleeps
                sleeps+=1
                if sleeps==3: (folder/'stop').touch()
            with patch.object(service,'ROOT',root), patch.object(service,'inspect',return_value=self.snapshot()), \
                 patch.object(service,'other_collector_alive',return_value=False), \
                 patch.object(service,'browser_available',return_value=True), \
                 patch.object(service.subprocess,'Popen',return_value=child) as launch, \
                 patch.object(service.time,'sleep',side_effect=sleep):
                service.run(config)
            self.assertEqual(launch.call_count,1)
            self.assertEqual(pointer.read_bytes(),b'{}')
            child.terminate.assert_not_called()

    def test_global_collector_marker_prevents_another_queue_from_starting(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            folder, queue, config=self.setup_project(root)
            def sleep(_): (folder/'stop').touch()
            with patch.object(service,'ROOT',root), patch.object(service,'inspect',return_value={}), \
                 patch.object(service,'other_collector_alive',return_value=True), \
                 patch.object(service.subprocess,'Popen') as launch, patch.object(service.time,'sleep',side_effect=sleep):
                service.run(config)
            launch.assert_not_called()

    def test_clean_budget_restarts_and_completed_queue_advances(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            folder, queue, config=self.setup_project(root,batches=[dict(social=[],websites=[{}])])
            next_queue=root/'.research/next'
            next_queue.mkdir()
            (next_queue/'queue.json').write_bytes((queue/'queue.json').read_bytes())
            (next_queue/'runtime.json').write_text(json.dumps(dict(state='needs-review',reason='upstream-needs-review',
                                                                   current_batch=None,processed_batches=0)))
            values=json.loads(config.read_text());values['queues'].append(str(next_queue))
            config.write_text(json.dumps(values))
            (queue/'runtime.json').write_text('{}')
            launches=[]
            def launch(command,**kwargs):
                launches.append(command)
                child=Mock(pid=100+len(launches),returncode=0)
                child.poll.return_value=0
                return child
            def inspect(root, target):
                if target == queue and len(launches) >= 2:
                    return self.snapshot(state='queue-processed',completed_batches=1)
                return self.snapshot() if target == queue else self.snapshot(state='needs-review')
            def sleep(_):
                if len(launches)>=3: (folder/'stop').touch()
            with patch.object(service,'ROOT',root), patch.object(service,'inspect',side_effect=inspect), \
                 patch.object(service,'other_collector_alive',return_value=False), \
                 patch.object(service.subprocess,'Popen',side_effect=launch), patch.object(service.time,'sleep',side_effect=sleep):
                service.run(config)
            self.assertEqual([command[command.index('--output')+1] for command in launches],[str(queue),str(queue),str(next_queue)])

    def test_next_web_only_batch_can_run_while_later_social_batches_wait(self):
        with tempfile.TemporaryDirectory() as temporary:
            queue=Path(temporary)
            (queue/'queue.json').write_text(json.dumps(dict(batches=[dict(social=[],websites=[{}]),dict(social=[{}],websites=[])])))
            self.assertFalse(service.pending_social(queue,self.snapshot()))
            self.assertTrue(service.pending_social(queue,self.snapshot(completed_batches=1)))


if __name__ == '__main__':
    unittest.main()
