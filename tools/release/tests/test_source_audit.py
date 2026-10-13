import hashlib,json,sys,tempfile,unittest
from pathlib import Path
import subprocess

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from stage_code import audit
from sync_repository import deployed_source


class SourceAuditTests(unittest.TestCase):
    def test_startup_reuses_only_unchanged_artifact_in_managed_build_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);sha='a'*40;runtime=root/'.research/frontend-dev';runtime.mkdir(parents=True)
            (runtime/'runtime.json').write_text(json.dumps(dict(state='starting')),encoding='utf-8')
            jar=root/'.research/application-builds'/sha/'gradheat-backend-0.1.0.jar';jar.parent.mkdir(parents=True);jar.write_bytes(b'synthetic compiled artifact')
            build=dict(source_sha=sha,jar=str(jar),jar_sha256=hashlib.sha256(jar.read_bytes()).hexdigest())
            (runtime/'backend-build.json').write_text(json.dumps(build),encoding='utf-8')
            self.assertEqual(deployed_source(root),sha)
            jar.write_bytes(b'changed')
            self.assertIsNone(deployed_source(root))
            outside=root/'outside.jar';outside.write_bytes(b'synthetic compiled artifact');build['jar']=str(outside)
            (runtime/'backend-build.json').write_text(json.dumps(build),encoding='utf-8')
            self.assertIsNone(deployed_source(root))

    def git(self,root,*args):
        subprocess.run(['git',*args],cwd=root,check=True,capture_output=True)

    def test_all_blob_boundaries_private_values_and_binary_content_are_checked(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);self.git(root,'init','-q')
            (root/'frontend/src').mkdir(parents=True)
            first=root/'README.md';second=root/'frontend/src/a.ts'
            first.write_text('synthetic header\n000000 blob 30\n',encoding='utf-8')
            second.write_text('export const value = 1\n',encoding='utf-8')
            self.git(root,'add','--','README.md','frontend/src/a.ts')
            self.assertEqual(audit(':',root,needles=set())['source_files'],2)
            second.write_text('synthetic-private-value',encoding='utf-8');self.git(root,'add','--','frontend/src/a.ts')
            with self.assertRaisesRegex(ValueError,'private-value'):audit(':',root,needles={b'synthetic-private-value'})
            second.write_bytes(b'\x00binary');self.git(root,'add','--','frontend/src/a.ts')
            with self.assertRaisesRegex(ValueError,'binary-or-unexpected-size'):audit(':',root,needles=set())

    def test_data_path_is_rejected_in_the_complete_index(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);self.git(root,'init','-q')
            (root/'.research').mkdir();(root/'.research/synthetic.json').write_text('{}',encoding='utf-8')
            self.git(root,'add','--','.research/synthetic.json')
            with self.assertRaisesRegex(ValueError,'outside-maintained-source'):audit(':',root,needles=set())
