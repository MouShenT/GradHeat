import sys,unittest,tempfile
from types import SimpleNamespace
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from gradheat_workbench.corroboration import Corroborator,scope,digest,canonical,apply_public,origin,observations

class CorroborationTests(unittest.TestCase):
    def test_institute_catalogue_is_official_but_lookalike_host_is_not(self):
        sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'tools/research'))
        with tempfile.TemporaryDirectory() as temp:
            row=dict(unit='中国科学院软件研究所',year=2027,major_code='081200',
                major_name='计算机科学与技术',department='软件研究所',
                subjects=['101','201','301','408'],source_url='https://is.cas.cn/catalogue')
            repo=SimpleNamespace(root=Path(temp),programmes={'one':row},data={})
            accepted=observations(repo)
            self.assertTrue(accepted)
            self.assertTrue(all(x['official'] for x in accepted))
            row['source_url']='https://lookalikecas.cn/catalogue'
            self.assertTrue(all(not x['official'] for x in observations(repo)))

    def row(self,**changes):
        return dict(unit='样本大学',year=2026,department='001计算机学院',major_name='计算机技术',cutoff_text='325',**changes)
    def obs(self,provider,value='325',official=False,row=None):
        key=scope(row or self.row(),'history')
        x=dict(scope=key,scope_id=digest(key),field='cutoff_text',value=canonical(value),origin_id=provider,official=official)
        x['id']=digest(x);return x
    def test_three_origins_remove_pending_and_note_official_gap(self):
        check=Corroborator([self.obs(o) for o in ('repo-author','institution-a','institution-b')])
        row=dict(self.row(),status='待验证')
        payload=dict(programmes=[],history=[row],cutoff_rows=[],admission_groups=[])
        apply_public(payload,check)
        self.assertEqual(row['status'],'三源一致')
        self.assertEqual(row['verification']['cutoff_text']['agreeing_sources'],3)
        self.assertIn('未找到',payload['official_notes'][0]['note'])
        self.assertNotIn('source_url',str(payload))
    def test_copies_of_one_origin_are_one_vote(self):
        c=Corroborator([self.obs('same-provider')]*4+[self.obs('other')])
        verdict,_=c.decision(self.row(),'history','cutoff_text','325')
        self.assertEqual(verdict['state'],'two-source-agreement');self.assertEqual(verdict['agreeing_sources'],2)
        self.assertEqual(origin({'repository':'wenliang90/408exam'}),origin({'repository':'csseky/cskaoyan'}))
    def test_year_and_pool_cannot_be_borrowed(self):
        newer=self.row();newer['year']=2027
        special=self.row(special_scope='退役士兵')
        c=Corroborator([self.obs('a'),self.obs('b',row=newer),self.obs('c',row=special)])
        verdict,_=c.decision(self.row(),'history','cutoff_text','325')
        self.assertEqual(verdict['agreeing_sources'],1)
    def test_provider_with_conflicting_values_cannot_vote_twice(self):
        c=Corroborator([self.obs('a'),self.obs('a','330'),self.obs('b'),self.obs('c')])
        self.assertEqual(c.decision(self.row(),'history','cutoff_text','325')[0]['agreeing_sources'],2)
        self.assertEqual(len(c.decisions()),2)
    def test_official_conflict_stays_visible(self):
        c=Corroborator([self.obs(o) for o in ('a','b','c')]+[self.obs('school','330',True)])
        verdict,record=c.decision(self.row(),'history','cutoff_text','325')
        self.assertEqual(verdict['state'],'conflict');self.assertEqual(verdict['official_state'],'conflict')
        self.assertTrue(record['competing_values'])
    def test_two_sources_remove_pending_but_one_source_does_not(self):
        c=Corroborator([self.obs('a'),self.obs('b')])
        row=dict(self.row(),status='待验证')
        apply_public(dict(programmes=[],history=[row],cutoff_rows=[],admission_groups=[]),c)
        self.assertEqual(row['status'],'两源一致')
        self.assertEqual(Corroborator([self.obs('a')]*3).decision(self.row(),'history','cutoff_text','325')[0]['state'],'pending')
    def test_confirmation_is_field_specific(self):
        c=Corroborator([self.obs(o) for o in ('a','b','c')])
        row=dict(self.row(),retest_text='100',status='待验证')
        apply_public(dict(programmes=[],history=[row],cutoff_rows=[],admission_groups=[]),c)
        self.assertEqual(row['status'],'部分信息三源一致')
        self.assertEqual(row['verification']['retest_text']['state'],'pending')

if __name__=='__main__':unittest.main()
