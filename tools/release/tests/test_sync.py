"""Real isolated Git repositories; no network or production data."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from stage_code import allowed, audit
from sync_repository import deployed_source, update_state, lock, LockBusy
from check_source import immutable_migrations


class SyncTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.run_git('init','-b','main');self.run_git('config','user.email','synthetic@example.test')
        self.run_git('config','user.name','Synthetic Test')
        (self.root/'README.md').write_text('Synthetic source\n',encoding='utf-8')
        self.run_git('add','README.md');self.run_git('commit','-qm','base')
        self.run_git('update-ref','refs/remotes/origin/main','HEAD')

    def run_git(self,*args):
        return subprocess.check_output(['git',*args],cwd=self.root,stderr=subprocess.DEVNULL).decode().strip()

    def test_raw_data_and_generated_inputs_are_never_source(self):
        for path in ('.research/raw.json','crawler/data/source.jsonl','config/collection-input.detailed-2027.json',
                     'frontend/src/sample.json','infra/docker/.env','docs/units/real.md','frontend/node_modules/file.js'):
            self.assertFalse(allowed(path),path)
        for path in ('frontend/src/views/GamePage.vue','python_service/gradheat_core/intelligence.py',
                     'crawler/sql/010_school_intelligence.sql','config/collection-input.example.json',
                     'backend/src/main/java/cn/gradheat/api/AdmissionsController.java'):
            self.assertTrue(allowed(path),path)

    def test_tree_audit_rejects_previously_tracked_data_and_secrets(self):
        (self.root/'README.md').write_text('SYNTHETIC_PRIVATE_TOKEN_1234',encoding='utf-8')
        self.run_git('add','README.md');self.run_git('commit','-qm','secret')
        with self.assertRaises(ValueError):audit('HEAD',root=self.root,needles={b'SYNTHETIC_PRIVATE_TOKEN_1234'})
        (self.root/'data.json').write_text('{}',encoding='utf-8')
        self.run_git('add','data.json');self.run_git('commit','-qm','data')
        with self.assertRaises(ValueError):audit('HEAD',root=self.root,needles=set())

    def test_uncommitted_changes_are_preserved(self):
        (self.root/'README.md').write_text('Local work\n',encoding='utf-8')
        self.assertEqual(update_state(self.root)['state'],'local-changes-preserved')
        self.assertEqual((self.root/'README.md').read_text(),'Local work\n')

    def test_untracked_local_data_does_not_trigger_staging(self):
        (self.root/'local-data.json').write_text('{"synthetic":true}',encoding='utf-8')
        self.assertEqual(update_state(self.root)['state'],'up-to-date')
        self.assertEqual(self.run_git('ls-files'),'README.md')

    def test_untracked_business_code_blocks_update(self):
        folder=self.root/'frontend/src';folder.mkdir(parents=True)
        (folder/'new.ts').write_text('export const edited = true',encoding='utf-8')
        self.assertEqual(update_state(self.root)['state'],'local-changes-preserved')

    def test_fast_forward_and_divergence_are_distinct(self):
        base=self.run_git('rev-parse','HEAD')
        self.run_git('checkout','-qb','remote')
        (self.root/'README.md').write_text('Remote source\n',encoding='utf-8')
        self.run_git('add','README.md');self.run_git('commit','-qm','remote')
        remote=self.run_git('rev-parse','HEAD');self.run_git('update-ref','refs/remotes/origin/main',remote)
        self.run_git('checkout','main')
        self.assertEqual(update_state(self.root)['state'],'fast-forward-available')
        self.assertEqual(self.run_git('rev-parse','HEAD'),base)
        (self.root/'AGENTS.md').write_text('Local source\n',encoding='utf-8')
        self.run_git('add','AGENTS.md');self.run_git('commit','-qm','local')
        self.assertEqual(update_state(self.root)['state'],'diverged-preserved')

    def test_applied_migration_cannot_be_changed(self):
        folder=self.root/'crawler/sql';folder.mkdir(parents=True)
        migration=folder/'002_research_ingest.sql';migration.write_bytes(b'CREATE TABLE example(id INT);\r\n')
        self.run_git('add','.');self.run_git('commit','-qm','migration')
        previous=self.run_git('rev-parse','HEAD')
        migration.write_bytes(b'DROP TABLE example;\r\n')
        self.run_git('add','.');self.run_git('commit','-qm','changed')
        with self.assertRaises(ValueError):immutable_migrations(previous,'HEAD',self.root)

    def test_configured_build_is_not_a_ready_deployment(self):
        folder=self.root/'.research/frontend-dev';folder.mkdir(parents=True)
        (folder/'backend-build.json').write_text('{"source_sha":"new"}',encoding='utf-8')
        self.assertIsNone(deployed_source(self.root))
        (folder/'runtime.json').write_text('{"state":"ready","backend_source_sha":"old"}',encoding='utf-8')
        self.assertEqual(deployed_source(self.root),'old')
        (folder/'runtime.json').write_text('{"state":"failed","backend_source_sha":"new"}',encoding='utf-8')
        self.assertIsNone(deployed_source(self.root))

    def test_existing_collector_lock_defers_update(self):
        with lock(self.root/'.research/daily-update'):
            with self.assertRaises(LockBusy):
                with lock(self.root/'.research/daily-update'):
                    self.fail('A second owner acquired the collector lock')


if __name__=='__main__':unittest.main()
