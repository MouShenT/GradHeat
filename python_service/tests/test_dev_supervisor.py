import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools/application'))
import dev_supervisor
import launcher
from runtime_json import write_runtime


class SupervisorTests(unittest.TestCase):
    def test_short_reader_lock_preserves_old_receipt_until_atomic_replacement(self):
        with tempfile.TemporaryDirectory() as directory:
            pointer=Path(directory)/'runtime.json';pointer.write_text('{"state":"old"}',encoding='utf-8')
            original=Path.replace;calls=0
            def replace(path,target):
                nonlocal calls
                calls+=1
                if calls<=2:
                    self.assertEqual(json.loads(pointer.read_text())['state'],'old')
                    raise PermissionError('synthetic reader lock')
                return original(path,target)
            with patch.object(Path,'replace',new=replace),patch('runtime_json.time.sleep'):
                write_runtime(pointer,dict(state='new',components={'frontend':'ready'}))
            self.assertEqual(json.loads(pointer.read_text()),dict(state='new',components={'frontend':'ready'}))
            self.assertEqual(list(pointer.parent.glob('*.tmp')),[])

    def test_permanent_denial_leaves_original_receipt_intact(self):
        with tempfile.TemporaryDirectory() as directory:
            pointer=Path(directory)/'runtime.json';pointer.write_bytes(b'{"state":"old"}')
            with patch.object(Path,'replace',side_effect=PermissionError('synthetic denial')),patch('runtime_json.time.sleep'):
                with self.assertRaises(PermissionError):write_runtime(pointer,dict(state='new'))
            self.assertEqual(pointer.read_bytes(),b'{"state":"old"}')
            self.assertEqual(list(pointer.parent.glob('*.tmp')),[])

    def test_unready_api_does_not_stop_repository_checks_or_create_duplicates(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);folder=root/'runtime';folder.mkdir()
            processes=[]
            def start(*args, **kwargs):
                process=Mock();process.pid=100+len(processes);process.poll.return_value=None
                process.terminate.side_effect=lambda: setattr(process.poll, 'return_value', 0)
                processes.append(process)
                return process,Mock()
            sleeps=0
            def sleep(_):
                nonlocal sleeps
                sleeps+=1
                if sleeps==20:(folder/'stop').touch()
            config=dict(runtime_dir=str(folder),task_name='synthetic',node='node',python='python',java='java',jar='app.jar',repository_sync=True)
            with patch.object(dev_supervisor,'ROOT',root),patch.object(dev_supervisor,'start',side_effect=start) as launch,patch.object(dev_supervisor,'reachable',return_value=False),patch.object(dev_supervisor.time,'monotonic',side_effect=[0]+[100]*30),patch.object(dev_supervisor.time,'sleep',side_effect=sleep):
                dev_supervisor.run(config)
            sync_calls=[c for c in launch.call_args_list if 'pull' in c.args[0]]
            self.assertEqual(len(sync_calls),1)
            self.assertIn('--deploy',sync_calls[0].args[0])
            self.assertEqual(len(processes),3)

    def test_failed_discovery_retains_phase_without_private_details_in_status(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'frontend/dist').mkdir(parents=True)
            (root/'frontend/dist/index.html').touch();jar=root/'app.jar';jar.touch()
            args=SimpleNamespace(jar=str(jar),java='java',java_port=18731,python_port=18732,no_worker=True)
            credentials={key:'synthetic-private-value' for key in ('MYSQL_USER','MYSQL_PASSWORD','MYSQL_DATABASE','REDIS_PASSWORD','RABBITMQ_USER','RABBITMQ_PASSWORD')}
            failure=SimpleNamespace(returncode=1,stderr='synthetic-private-value',stdout='')
            with patch.object(launcher,'ROOT',root),patch.object(launcher,'check_port'),patch.object(launcher,'env_file',return_value=credentials),patch.object(launcher,'ssh_connection',return_value=(['ssh'],'example')),patch.object(launcher.subprocess,'run',return_value=failure):
                with self.assertRaises(RuntimeError):launcher.run(args)
            folder=root/'.research/application-runtime-18731'
            status=(folder/'runtime.json').read_text(encoding='utf-8')
            self.assertEqual(json.loads(status)['failure_phase'],'infrastructure-discovery')
            self.assertNotIn('synthetic-private-value',status)
            self.assertIn('synthetic-private-value',(folder/'private.log').read_text())
