import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'crawler'),str(ROOT/'tools/research')]
import run_import_research as importer


class FullSourceImportTests(unittest.TestCase):
    def test_sources_outside_priority_dossiers_are_stored_without_qualification(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);work=root/'work';snapshot=root/'snapshot'
            def save(path,value):
                path.parent.mkdir(parents=True,exist_ok=True)
                path.write_text(json.dumps(value,ensure_ascii=False),encoding='utf-8')
            save(snapshot/'comparison.json',dict(as_of='2026-10-09',target_year=2027,
                units=[dict(name='重点大学',group='985')],programmes=[],checked_claims=[]))
            sha=hashlib.sha256((snapshot/'comparison.json').read_bytes()).hexdigest()
            save(snapshot/'manifest.json',dict(outputs=[dict(path='comparison.json',sha256=sha)]))
            save(work/'comparison-draft-pointer.json',dict(path=str(snapshot),snapshot_id='fixture'))
            for filename in ['official-table-facts.json','admission-statistics-candidates.json','dossiers.json',
                             'material-availability.json','missing-fields.json','first-pool-candidates.json']:
                save(work/filename,[])
            save(work/'live-sources.json',[dict(unit='重点大学',year=2027,url='https://a.edu.cn/catalogue'),
                dict(unit='新增候选大学',year=2027,url='https://b.edu.cn/catalogue')])
            migration=root/'002.sql';migration.write_text('-- fixture',encoding='utf-8')
            with patch.object(importer,'ROOT',root),patch.object(importer,'OUT',root/'output'), \
                    patch.object(importer,'MIGRATION',migration),patch.object(importer.d,'WORK',work):
                package,_=importer.prepare()
            rows=package['records']
            candidate=next(r for r in rows if r['kind']=='unit' and r['unit_name']=='新增候选大学')
            self.assertTrue(candidate['payload_json']['candidate_only'])
            self.assertIsNone(candidate['eligible_11408'])
            self.assertIsNone(candidate['ordinary_quota'])
            self.assertEqual(package['manifest']['counts']['source_observation'],2)
            self.assertFalse(any(r['kind']=='programme' for r in rows))
            self.assertEqual(package['manifest']['approved_ranking_pools'],0)


if __name__=='__main__':unittest.main()
