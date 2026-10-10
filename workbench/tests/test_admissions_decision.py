import copy
import hashlib
import sys
import tempfile
import unittest
from pathlib import Path
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from gradheat_workbench.admissions_decision import evaluate_public, publication_version, render_report
from gradheat_workbench.history_alignment import align_history
from gradheat_workbench.models import ComparisonInput
from gradheat_workbench.sessions import canonical
from gradheat_workbench.app import create_app
from test_workbench import fixture


def programme(n, **changes):
    return dict(id=str(n)*24, unit='样本大学', year=2027, department='001计算机学院',
        major_name='计算机科学与技术', major_code='081200', degree_type='学术学位', mode='全日制',
        eligible_11408=True, subjects=['101','201','301','408'], plan_text='专业25（不含推免）', ordinary_quota=None) | changes


class AlignmentTests(unittest.TestCase):
    def history(self, **changes):
        return dict(id='h', unit='样本大学', year=2026, department='计算机学院', major_name='计算机科学与技术', exam_text='11408') | changes

    def test_other_major_in_same_college_is_not_attached(self):
        p=programme(1)
        linked=align_history([p],[self.history(),self.history(id='other',major_name='人工智能')])[p['id']]
        self.assertEqual(linked['matched'],['h'])

    def test_unknown_college_cannot_choose_between_two_colleges(self):
        p,q=programme(1),programme(2,department='网络学院')
        linked=align_history([p,q],[self.history(department=None)])
        self.assertTrue(all(x['matched']==[] and x['ambiguous']==['h'] for x in linked.values()))

    def test_degree_mode_and_major_code_conflicts_are_separate(self):
        p=programme(1)
        for changes in [{'degree_type':'专业学位'},{'mode':'非全日制'},{'major_code':'085404'}]:
            self.assertEqual(align_history([p],[self.history(**changes)])[p['id']]['matched'],[])

    def test_past_subject_change_remains_historical_context(self):
        p=programme(1)
        linked=align_history([p],[self.history(exam_text='22408',year=2025)])[p['id']]
        self.assertEqual(linked['matched'],['h'])


class PublicDecisionTests(unittest.TestCase):
    def setUp(self):
        self.payload=dict(data_as_of='2026-10-05',programmes=[programme(1),programme(2,major_code='085404',major_name='计算机技术',degree_type='专业学位')],history=[])
        self.request=dict(profile={},weights=dict(research=1,location=1,cost=1,career=1,training=1),candidates=[{'programme_id':p['id']} for p in self.payload['programmes']])

    def calculate(self):
        return evaluate_public(self.payload,ComparisonInput(**self.request))

    def test_blank_ratings_remain_unknown_including_professional_degree(self):
        result=self.calculate()
        self.assertEqual(len(result['baseline']['intervals']),2)
        self.assertTrue(all(s['low']==0 and s['high']==10 for s in result['baseline']['intervals'].values()))
        self.assertIsNone(result['cards'][0]['programme']['ordinary_quota'])

    def test_conditions_exclude_even_high_scoring_candidate(self):
        self.request['profile']={'degrees':['学术学位']}
        self.request['candidates'][1]['ratings']={d:dict(low=10,high=10) for d in self.request['weights']}
        result=self.calculate()
        self.assertEqual(result['cards'][1]['hard_constraint_status'],'blocked')
        self.assertNotIn(programme(2)['id'],result['baseline']['intervals'])

    def test_known_ratings_and_weight_sensitivity_do_not_invent_probabilities(self):
        self.request['weights']=dict(research=1.1,location=1,cost=0,career=0,training=0)
        self.request['candidates'][0]['ratings']=dict(research=dict(low=9,high=9),location=dict(low=1,high=1))
        self.request['candidates'][1]['ratings']=dict(research=dict(low=1,high=1),location=dict(low=9,high=9))
        result=self.calculate()
        self.assertEqual(result['baseline']['certain_best'],[programme(1)['id']])
        self.assertEqual(result['stable_certain_best'],[])
        self.assertEqual(len(result['sensitivity']),4)
        self.assertNotIn('probability',canonical(result))

    def test_report_and_results_only_contain_public_facts(self):
        result=self.calculate()
        report=render_report(result)
        for value in [canonical(result),report]:
            self.assertNotIn('source_url',value)
            self.assertNotIn('https://',value)
        self.assertIn('专业25（不含推免）',report)
        self.assertEqual(result['data_version'],publication_version(self.payload))


class MemoryArchive:
    """API isolation only; the production archive is separately checked in MySQL."""
    def __init__(self):self.rows={}
    def save(self,result):
        report=render_report(result)
        cid=hashlib.sha256(canonical(dict(result=result,report_md=report)).encode()).hexdigest()
        reused=cid in self.rows
        self.rows.setdefault(cid,dict(comparison_id=cid,result=copy.deepcopy(result),report_md=report,title=result['input']['title'],created_at='2026-10-05T00:00:00Z',candidate_count=len(result['cards'])))
        return dict(comparison_id=cid,reused=reused)
    def get(self,cid):return self.rows[cid]
    def list(self):return list(self.rows.values())


class PublicAPITests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        root=Path(temp.name);folder=fixture(root)
        self.client=TestClient(create_app(root,folder,comparison_archive=MemoryArchive()),base_url='http://127.0.0.1')
        self.client.__enter__();self.addCleanup(self.client.__exit__,None,None,None)
        response=self.client.get('/api/admissions');p=response.json()['programmes'][0]
        self.request=dict(data_version=response.headers['X-Data-Version'],candidates=[dict(programme_id=p['id'])])

    def test_data_update_requires_recalculation(self):
        req=dict(self.request,data_version='f'*64)
        self.assertEqual(self.client.post('/api/admissions/compare',json=req).status_code,409)
        self.assertEqual(self.client.post('/api/admissions/comparisons',json=req).status_code,409)

    def test_compare_save_export_and_reopen_preserve_frozen_values(self):
        result=self.client.post('/api/admissions/compare',json=self.request)
        self.assertEqual(result.status_code,200)
        self.assertNotIn('source_url',result.text)
        first=self.client.post('/api/admissions/comparisons',json=self.request).json();cid=first['comparison_id']
        self.assertTrue(self.client.post('/api/admissions/comparisons',json=self.request).json()['reused'])
        self.client.app.state.admissions.payload['data_as_of']='2026-10-06'
        stored=self.client.get('/api/admissions/comparisons/'+cid).json()['result']
        self.assertEqual(stored['data_as_of'],result.json()['data_as_of'])
        export=self.client.get('/api/admissions/comparisons/'+cid+'/export?format=md')
        self.assertEqual(export.status_code,200);self.assertIn('attachment',export.headers['content-disposition'])
        self.assertEqual(len(self.client.get('/api/admissions/comparisons').json()['items']),1)

    def test_missing_invalid_and_external_origin_rejected(self):
        req=copy.deepcopy(self.request);req['candidates'][0]['programme_id']='f'*24
        self.assertEqual(self.client.post('/api/admissions/compare',json=req).status_code,404)
        self.assertEqual(self.client.get('/api/admissions/comparisons/invalid').status_code,404)
        self.assertEqual(self.client.post('/api/admissions/comparisons',json=self.request,headers={'Origin':'https://external.invalid'}).status_code,403)

    def test_database_failure_does_not_claim_saved(self):
        def fail(result):raise ConnectionError('private diagnostic')
        self.client.app.state.comparison_archive.save=fail
        response=self.client.post('/api/admissions/comparisons',json=self.request)
        self.assertEqual(response.status_code,503)
        self.assertNotIn('private diagnostic',response.text)


if __name__=='__main__':unittest.main()
