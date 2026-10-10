import hashlib,json,sys,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from gradheat_workbench.admissions import build_public,interview_ratio,integer
from gradheat_workbench.data_store import AdmissionsStore


class AdmissionsTests(unittest.TestCase):
    def test_ratio_is_retest_over_admitted(self):
        self.assertEqual(interview_ratio('150','114'),1.3158)
        self.assertIsNone(interview_ratio('316+2专项','232+2专项'))
        self.assertIsNone(interview_ratio('6+29调剂','6+6调剂'))
        self.assertIsNone(interview_ratio(None,114))
        self.assertIsNone(interview_ratio(50,0))
        self.assertIsNone(interview_ratio(20,30))
        self.assertEqual(integer(0),0)

    def repo(self,root):
        rows=[dict(id=str(n)*24,unit='样本大学',cohort=2027,department='计算机学院',major_code='081200',major_name='计算机科学与技术',
            degree_type='学术学位',mode='全日制',subjects=['101','201','301','408'],eligible_11408=True,planned_major_raw=plan,
            source_url='https://example.edu.cn/private-source',source_sha256='a'*64,source_artifact='D:/secret/original.pdf') for n,plan in [(1,'25，不含推免'),(2,'30，不含推免')]]
        return SimpleNamespace(root=root,programmes={p['id']:p for p in rows},units={'样本大学':dict(name='样本大学',group='985')},data={'as_of':'2026-10-05','history_candidates':[]})

    def test_public_projection_has_no_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            payload=build_public(self.repo(Path(tmp)))
            text=json.dumps(payload,ensure_ascii=False)
            for forbidden in ('source_url','source_sha256','source_artifact','https://','private-source','secret'):
                self.assertNotIn(forbidden,text)
            self.assertEqual(payload['counts']['programmes'],1)
            self.assertEqual(payload['programmes'][0]['plan_status'],'多版人数待核')
            self.assertIsNone(payload['programmes'][0]['ordinary_quota'])

    def test_ambiguous_subject_versions_stay_unknown(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo=self.repo(Path(tmp));list(repo.programmes.values())[1]['eligible_11408']=False
            self.assertIsNone(build_public(repo)['programmes'][0]['eligible_11408'])

    def test_changed_mirror_is_loaded_but_corrupt_version_is_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);store=AdmissionsStore(root,self.repo(root))
            old=store.get();payload={**old,'last_checked':'2026-10-06'}
            raw=json.dumps(payload,ensure_ascii=False).encode();sha=hashlib.sha256(raw).hexdigest()
            folder=root/'.research/admissions-data';folder.mkdir(parents=True)
            path=folder/(sha+'.json');path.write_bytes(raw)
            (folder/'latest.json').write_text(json.dumps({'version_id':sha,'path':str(path)}),encoding='utf-8')
            self.assertEqual(store.get()['last_checked'],'2026-10-06')
            bad=folder/'bad.json';bad.write_text('{}',encoding='utf-8')
            (folder/'latest.json').write_text(json.dumps({'version_id':'b'*64,'path':str(bad)}),encoding='utf-8')
            self.assertEqual(store.get()['last_checked'],'2026-10-06')

    def test_history_count_status_and_year_are_retained(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);folder=root/'.research/unit-dossiers-20261001';folder.mkdir(parents=True)
            rows=[{'aligned':True,'department':'计算机学院','fields':{'专业名称':'计算机技术','初试科目':'11408','复试人数':'316+2专项','拟录取人数':'232+2专项','分数线':'325','拟录取分数':'355【325-417】'}},
                  {'aligned':False,'fields':{'专业名称':'不能对齐'}}]
            (folder/'dossiers.json').write_text(json.dumps([{'unit':'样本大学','secondary':{'2026':rows}}],ensure_ascii=False),encoding='utf-8')
            public=build_public(self.repo(root));self.assertEqual(len(public['history']),1)
            row=public['history'][0];self.assertEqual(row['year'],2026);self.assertEqual(row['status'],'待核')
            self.assertEqual(row['retest_text'],'316+2专项');self.assertIsNone(row['interview_admit_ratio'])

    def test_unknown_year_catalogue_cannot_add_2027_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);folder=root/'.research/github-sources';folder.mkdir(parents=True)
            (folder/'candidates.json').write_text(json.dumps([{'id':'unknown','kind':'catalogue','unit':'另一个大学','year':None,'subjects':['101','201','301','408'],'plan_text':'999'}]),encoding='utf-8')
            payload=build_public(self.repo(root))
            self.assertEqual(len(payload['programmes']),1)
            self.assertNotIn('999',str(payload['programmes']))

    def test_conflicting_scope_does_not_enter_history_table(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);folder=root/'.research/github-sources';folder.mkdir(parents=True)
            (folder/'candidates.json').write_text(json.dumps([{'id':'conflict','kind':'history','unit':'样本大学','year':2026,'scope_status':'scope-conflict','cutoff_text':'264'}]),encoding='utf-8')
            self.assertEqual(build_public(self.repo(root))['history'],[])

    def test_retest_distribution_cannot_become_admitted_distribution(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);folder=root/'.research/github-sources';folder.mkdir(parents=True)
            (folder/'candidates.json').write_text(json.dumps([{'id':'distribution','kind':'distribution','unit':'样本大学','year':2025,'population':'retest_pool','exam_text':'22408','n':120,'minimum':310}]),encoding='utf-8')
            row=build_public(self.repo(root))['admission_groups'][0]
            self.assertEqual(row['status'],'复试分组待核');self.assertEqual(row['exam_text'],'22408')

if __name__=='__main__':unittest.main()
