import hashlib,json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import Mock

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools/research'))
from collect_community_sources import codebrick_admission_samples,import_sources


def original():
    return json.dumps(dict(code=0,data=dict(schoolId=7,schoolName='甲大学',programName='乙学院 软件工程',admitType='unified',years=[
        dict(year=2026,sourceLevel='official',sourceUrl='https://example.edu/notice',enrolledCount=12,retestCount=3,poolCount=0,
             recordCount=15,distPopulation='enrolled',retestLineTotal=310,admitMinTotal=325,retestEliminationRate=20,
             retestWeight=dict(reliable=True,firstPct=60,retestPct=40)),
        dict(year=2025,sourceLevel='secondary',sourceUrl=None,enrolledCount=9,retestCount=0,poolCount=0,
             recordCount=9,distPopulation='enrolled',retestLineTotal=305,admitMinTotal=305,retestEliminationRate=0)
    ])),ensure_ascii=False).encode()


class CodebrickCommunityTests(unittest.TestCase):
    def test_lists_do_not_become_official_lines_or_complete_ordinary_pools(self):
        rows=codebrick_admission_samples(original(),'甲大学')
        self.assertEqual(rows[0]['observed_retest_list_minimum'],310)
        self.assertEqual(rows[0]['admitted_total_minimum'],325)
        self.assertEqual(rows[0]['site_claimed_source_level'],'official')
        self.assertEqual(rows[0]['source_kind'],'community-database')
        self.assertEqual(rows[1]['site_reported_elimination_rate'],0)
        for row in rows:
            for key in ('official_cutoff','elimination_rate','ordinary_quota','mode','population','route','special'):
                self.assertIsNone(row[key])

    def test_failed_identity_and_duplicate_year_are_rejected(self):
        with self.assertRaises(ValueError):codebrick_admission_samples(original(),'其他大学')
        payload=json.loads(original());payload['code']=401
        with self.assertRaises(ValueError):codebrick_admission_samples(json.dumps(payload).encode(),'甲大学')
        payload=json.loads(original());payload['data']['years'].append(payload['data']['years'][0])
        with self.assertRaises(ValueError):codebrick_admission_samples(json.dumps(payload).encode(),'甲大学')

    def test_raw_json_is_reparsed_before_any_archive_or_database_work(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);path=root/'original.json';path.write_bytes(original())
            row=dict(unit='甲大学',scope='institution',site_url='https://www.codebrick.tech/practice/school-admit',
                     score_url='https://www.codebrick.tech/api/school/admit/7/stats?programName=test',pages=[],scores=[],
                     admission_original=dict(source_artifact=str(path),source_sha256=hashlib.sha256(path.read_bytes()).hexdigest()),
                     admission_samples=codebrick_admission_samples(path.read_bytes(),'甲大学'))
            row['admission_samples'][0]['admitted_sample_count']=99;con=Mock()
            with self.assertRaises(ValueError):import_sources(con,root,[row],['甲大学'])
            con.cursor.assert_not_called()
            row['admission_samples']=codebrick_admission_samples(path.read_bytes(),'甲大学');row['scores']=[dict(cutoff=310)]
            with self.assertRaises(ValueError):import_sources(con,root,[row],['甲大学'])
            con.cursor.assert_not_called()


if __name__=='__main__':unittest.main()
