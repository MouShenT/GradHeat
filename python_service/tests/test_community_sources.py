import hashlib,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import Mock
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'python_service'));sys.path.insert(0,str(ROOT/'tools/research'))
from gradheat_core.community_sources import score_rows,source_family
from gradheat_core.decision_inputs import resolve_inputs

TABLE='''## 普通计划
| 年份 | 类型 | 专业 | 专业课代码 | 政治 | 英语 | 数学 | 专业课 | 总分线 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2026 | 学硕 | - | 11408 | 35 | 35 | ？ | - | 290 |
| 2026 | 专硕 | - | 22408 | 35 | 35 | 53 | 53 | 346 |
| 2025 | 学硕 | - | 11408 | 34 | 34 | 51 | 51 | 264 |
## 退役大学生士兵计划
| 年份 | 类型 | 专业 | 专业课代码 | 政治 | 英语 | 数学 | 专业课 | 总分线 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2026 | 学硕 | - | 11408 | - | - | - | - | 230 |
| 2025 | 学硕 | - | 11408 | - | - | - | - |  |
'''


class CommunityTests(unittest.TestCase):
    def fixture(self):
        programme=dict(id='a',unit='甲研究所',major_code='081200',major_name='计算机科学与技术',year=2027,mode='全日制')
        source=dict(unit=programme['unit'],scope='institution',site_url='https://a.example.org/',score_url='https://example.org/scores.md',scores=score_rows(TABLE))
        return programme,dict(community_sources=[source])

    def test_plan_unknown_cells_and_exam_scopes_are_preserved(self):
        rows=score_rows(TABLE);self.assertEqual(len(rows),4)
        self.assertEqual(rows[0]['score_limits'],dict(politics=35,english=35))
        self.assertFalse(rows[0]['special']);self.assertTrue(rows[-1]['special'])
        p,d=self.fixture();result=resolve_inputs(p,d,[])
        self.assertEqual(result['threshold'],290);self.assertEqual(result['threshold_basis'],'community-school-table')
        self.assertEqual(result['threshold_confidence'],.6);self.assertEqual(result['score_limits_year'],2026)
        self.assertIsNone(result['ordinary_quota'])
        p['major_code']='085404';self.assertIsNone(resolve_inputs(p,d,[])['threshold'])

    def test_official_conflict_wins_and_foreign_major_does_not_fill(self):
        p,d=self.fixture()
        d['decision_facts']=[dict(unit=p['unit'],major_code=p['major_code'],year=2026,route='first-choice',population='ordinary',mode='全日制',values=dict(cutoff=350),source_url='https://example.edu/notice')]
        self.assertEqual(resolve_inputs(p,d,[])['threshold'],350)
        self.assertEqual(resolve_inputs(p,d,[])['threshold_confidence'],.95)
        del d['decision_facts'];d['community_sources'][0]['scores'][0]['major_name']='网络空间安全'
        self.assertEqual(resolve_inputs(p,d,[])['threshold_year'],2025)

    def test_same_site_family_is_not_an_independent_vote(self):
        self.assertEqual(source_family('https://a.cskaoyan.cn/'),source_family('https://b.cskaoyan.cn/'))
        self.assertNotEqual(source_family('https://university.edu.cn/'),'cskaoyan.cn')

    def test_score_transcript_tamper_is_rejected_before_archive(self):
        from collect_community_sources import import_sources
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);path=root/'original.md';path.write_text(TABLE,encoding='utf-8')
            row=dict(unit='甲研究所',scope='institution',site_url='https://example.org/',score_url='https://example.org/scores.md',pages=[],
                     score_original=dict(source_artifact=str(path),source_sha256=hashlib.sha256(path.read_bytes()).hexdigest()),scores=score_rows(TABLE))
            row['scores'][0]['cutoff']=400;con=Mock()
            with self.assertRaises(ValueError):import_sources(con,root,[row],['甲研究所'])
            con.cursor.assert_not_called()


if __name__=='__main__':unittest.main()
