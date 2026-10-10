import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch,Mock
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient
from gradheat_python.collection_web import CollectionWeb
from gradheat_python.collection_plan import write_json,load_state
from gradheat_python.config import Settings
from gradheat_python.api import create_app
from gradheat_python.publication import FrozenPublication
from gradheat_python.handlers import AutonomousScope

ROOT=Path(__file__).resolve().parents[2]


class CollectionWebTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        (self.root/'config').mkdir()
        for name in ('collection-keywords.json','collection-policy.json'):
            (self.root/'config'/name).write_bytes((ROOT/'config'/name).read_bytes())
        self.settings=Settings(root=self.root,internal_token='synthetic-collection-token-'+'x'*32)
        self.auth={'X-GradHeat-Internal-Token':self.settings.internal_token}
        self.client=TestClient(create_app(self.settings,publications=FrozenPublication({'programmes':[],'units':[],'history':[]})))

    def tearDown(self):self.client.close();self.temp.cleanup()

    def test_authenticated_upload_freezes_only_pointer_and_progress_hides_raw_details(self):
        body={'tasks':[{'platform':'official','query':'合成检索'},{'platform':'github','repo':'test/public'}]}
        self.assertEqual(self.client.post('/internal/v1/collection/prepare',json=body).status_code,401)
        r=self.client.post('/internal/v1/collection/prepare',json=body,headers=self.auth)
        self.assertEqual(r.status_code,200);value=r.json();self.assertEqual(value['planned_jobs'],2)
        self.assertNotIn('tasks',value);self.assertNotIn('batch',value)
        folder=self.root/'.research/autonomous-collection'/value['batch_id'];state=load_state(folder)
        plan=json.loads((folder/'plan.json').read_text(encoding='utf-8'))
        state['jobs'][plan['jobs'][0]['id']]={'state':'needs-human','result':{'source_url':'https://example.edu/private','raw_html':'never-return'}}
        write_json(folder/'state.json',state)
        response=self.client.get('/internal/v1/collection/'+value['batch_id'],headers=self.auth)
        self.assertEqual(response.status_code,200);self.assertEqual(response.json()['incomplete_jobs'],1)
        self.assertNotIn('source_url',response.text);self.assertNotIn('never-return',response.text)

    def test_download_authentication_and_no_arbitrary_path(self):
        web=self.client.app.state.collection
        data=web.prepare({'tasks':[{'platform':'bili','query':'合成关键词'}]})
        write_json(web.batch(data['batch_id'])/'incomplete.json',{'tasks':[]})
        url='/internal/v1/collection/'+data['batch_id']+'/download/incomplete'
        self.assertEqual(self.client.get(url).status_code,401)
        self.assertEqual(self.client.get(url,headers=self.auth).json(),{'tasks':[]})
        for identifier in ('../private','batch-x','batch-20261010-'+'a'*12):
            with self.assertRaises(ValueError):web.batch(identifier)
        with self.assertRaises(ValueError):web.download(data['batch_id'],'private.log')

    def test_browser_action_uses_fixed_own_script_and_does_not_block_request(self):
        web=self.client.app.state.collection;fake=Mock();fake.poll.return_value=None
        with patch('gradheat_python.collection_web.subprocess.Popen',return_value=fake) as launch:
            self.assertEqual(web.open_browser()['state'],'opening')
            self.assertTrue(web.open_browser()['reused']);self.assertEqual(launch.call_count,1)
            self.assertEqual(Path(launch.call_args.args[0][-1]).name,'open_social_login.py')
        self.assertEqual(AutonomousScope.model_validate({'batch_id':'batch-20261010-'+'a'*12,'plan_sha':'b'*64}).retry_platforms,[])
        with self.assertRaises(ValueError):AutonomousScope.model_validate({'batch_id':'../private','plan_sha':'b'*64})

    def test_upload_rejects_private_credentials_and_oversized_body(self):
        for value in ({'tasks':[None]}, {'tasks':[{'platform':'official','query':[]}]}):
            r=self.client.post('/internal/v1/collection/prepare',headers=self.auth,json=value)
            self.assertEqual(r.status_code,422)
        r=self.client.post('/internal/v1/collection/prepare',headers=self.auth,json={'tasks':[{'platform':'xhs','query':'a','token':'private'}]})
        self.assertEqual(r.status_code,422)
        r=self.client.post('/internal/v1/collection/prepare',headers=self.auth,content=b'a'*5000001)
        self.assertEqual(r.status_code,413)


if __name__=='__main__':unittest.main()
