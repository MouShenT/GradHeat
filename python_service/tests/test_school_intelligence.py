import sys
from pathlib import Path
import unittest
from unittest.mock import AsyncMock, patch
import asyncio
import json
import tempfile

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'python_service'))
sys.path.insert(0,str(ROOT/'tools/research'))
from gradheat_core.intelligence import identify, heat_index, plausible_claims, PersonalProfile, VictoryInput, victory_indices, unique_units
from pydantic import ValidationError


class SchoolIntelligenceTests(unittest.TestCase):
    def test_name_variants_merge_and_generic_college_requires_parent(self):
        self.assertEqual(unique_units(['中国地质大学（北京）','中国地质大学(北京)']),['中国地质大学（北京）'])
        self.assertEqual(identify(dict(title='中国地质大学(北京)考研'),['中国地质大学（北京）'])[0]['unit'],'中国地质大学（北京）')
        self.assertEqual(identify(dict(title='数学科学学院研究生复试',query='考研'),['数学科学学院']),[])
        self.assertEqual(identify(dict(title='国科大数学科学学院研究生复试'),['数学科学学院'])[0]['unit'],'数学科学学院')

    def test_search_provider_missing_is_not_zero_and_window_integrity(self):
        from collect_search_indices import parse_indices
        item=dict(word='[{"name":"示例大学研究生院"}]',**{k:dict(startDate='2026-10-01',endDate='2026-10-04',data='10,,30,0') for k in ('all','pc','wise')})
        result=parse_indices(dict(data=dict(userIndexes=[item])),None,lambda key,s:s.split(','),'2026-10-10')[0]
        self.assertEqual(result['daily']['all'][1]['value'],None)
        self.assertEqual(result['value'],40/3);self.assertEqual(result['coverage'],.75)
        item['all']['data']=''
        empty=parse_indices(dict(data=dict(userIndexes=[item])),None,lambda key,s:s.split(','),'2026-10-10')[0]
        self.assertIsNone(empty['value']);self.assertEqual(empty['coverage'],0)
        item['all']['data']='10,20'
        with self.assertRaises(ValueError):parse_indices(dict(data=dict(userIndexes=[item])),None,lambda key,s:s.split(','),'2026-10-10')

    def test_timeout_recovers_prior_pages_and_partial_page(self):
        import mediacrawler_worker as worker
        with tempfile.TemporaryDirectory() as temp:
            checkpoint=Path(temp)/'result.json'
            checkpoint.write_text(json.dumps(dict(documents=[dict(platform='bili',content_id='a')],public_responses=[])),encoding='utf-8')
            checkpoint.with_suffix('.page.json').write_text(json.dumps(dict(documents=[dict(platform='bili',content_id='a'),dict(platform='bili',content_id='b')],public_responses=[])),encoding='utf-8')
            result=worker.read_checkpoint(dict(checkpoint=str(checkpoint)))
        self.assertEqual({d['content_id'] for d in result['documents']},{'a','b'})

    def test_broad_comparison_splits_schools_and_ambiguous_alias_is_not_assigned(self):
        units=['北京邮电大学','南京邮电大学','华东师范大学','华中师范大学','电子科技大学','西安电子科技大学']
        found=identify(dict(title='北邮和南邮计算机考研怎么选',query='11408 择校'),units)
        self.assertEqual({r['unit'] for r in found},{'北京邮电大学','南京邮电大学'})
        self.assertEqual(sum(r['weight'] for r in found),1)
        self.assertEqual(identify(dict(title='华师计算机考研',query='考研'),units),[])
        self.assertEqual([r['unit'] for r in identify(dict(title='西安电子科技大学考研',query='408'),units)],['西安电子科技大学'])
        self.assertEqual(identify(dict(title='北京邮电大学高考校园参观',query='北邮 考研'),units),[])

    def test_heat_dedup_recency_and_search_results_are_not_search_volume(self):
        def doc(n,likes=100,time='2026-10-01'):
            return dict(id=n,platform='xhs',content_id=n,published_at=time,observed_at='2026-10-10',metrics={'liked_count':likes})
        one=heat_index([doc('a')],[],'2026-10-10')
        self.assertEqual(one,heat_index([doc('a'),doc('a')],[],'2026-10-10'))
        self.assertGreater(heat_index([doc('a'),doc('b')],[],'2026-10-10')['heat_value'],one['heat_value'])
        self.assertGreater(one['heat_value'],heat_index([doc('a',time='2025-01-01')],[],'2026-10-10')['heat_value'])
        self.assertIsNone(heat_index([],[],'2026-10-10')['heat_value'])
        signal=dict(kind='search-index',provider='synthetic',value=200,reference_scale=1000,source_url='https://example.org/index',keyword='考研',window_start='2026-10-01',window_end='2026-10-09')
        complete=heat_index([doc('a')],[signal],'2026-10-10')
        self.assertEqual(complete['basis'],'discussion-and-search')
        self.assertEqual(complete,heat_index([doc('a')],[signal,signal],'2026-10-10'))
        signal['kind']='search-result-count'
        self.assertEqual(one,heat_index([doc('a')],[signal],'2026-10-10'))

    def test_impossible_claims_and_cross_school_numbers_rejected(self):
        doc=dict(id='a',title='北邮南邮计算机考研',text='2026 北邮 081200 复试线 999。2026 南邮 081200 复试线 330',url='https://example.org/a')
        claims=plausible_claims(doc,identify(doc,['北京邮电大学','南京邮电大学']))
        self.assertEqual(len(claims),1)
        self.assertEqual((claims[0]['unit'],claims[0]['year'],claims[0]['value']),('南京邮电大学',2026,330))

    def test_score_consistency_and_blank_profile(self):
        with self.assertRaises(ValidationError): PersonalProfile(score=300,politics=80,english=80,mathematics=140,computer=130)
        with self.assertRaises(ValidationError): PersonalProfile(score=float('inf'))
        self.assertEqual(PersonalProfile(politics=60,english=60,mathematics=100,computer=110).score,330)
        result=victory_indices(dict(programmes=[],history=[]),{},VictoryInput(data_version='a'*64,profile=PersonalProfile()))
        self.assertTrue(result['needs_profile']);self.assertEqual(result['ranking'],[])

    def fixture(self):
        programmes=[dict(id=n,unit=n,eligible_11408=True,year=2027,mode='全日制',group='211',major_code='081200',major_name='计算机',ordinary_quota=40) for n in ['甲','乙','丙']]
        payload=dict(programmes=programmes,history=[dict(id=n,year=2026,cutoff=320) for n in ['甲','乙']],historical_alignment={n:dict(matched=[n]) for n in ['甲','乙']})
        dossiers={n:dict(tier='211',heat=dict(heat_value=h)) for n,h in [('甲',20),('乙',80),('丙',10)]}
        return payload,dossiers

    def test_victory_improves_with_score_and_heat_penalizes_same_school(self):
        payload,dossiers=self.fixture()
        def run(score): return victory_indices(payload,dossiers,VictoryInput(data_version='a'*64,profile=PersonalProfile(score=score)))
        a,b=run(350),run(380)
        av={r['unit']:r['victory_index'] for r in a['ranking']};bv={r['unit']:r['victory_index'] for r in b['ranking']}
        self.assertGreater(av['甲'],av['乙']);self.assertGreater(bv['甲'],av['甲']);self.assertIsNone(av['丙'])
        self.assertTrue(a['game_converged']);self.assertTrue(all(v is None or 0<=v<=100 for v in av.values()))
        self.assertEqual(a,run(350))

    def test_page_collection_deduplicates_and_stops_on_restriction(self):
        import mediacrawler_worker as worker
        values=[dict(state='collected',search_items=20,has_more=True,documents=[dict(platform='bili',content_id='a')]),
                dict(state='collected',search_items=20,has_more=True,documents=[dict(platform='bili',content_id='a'),dict(platform='bili',content_id='b')]),
                dict(state='needs-human',reason='verification',search_items=0,documents=[])]
        with patch.object(worker,'collect_page',new=AsyncMock(side_effect=values)) as page, patch.object(worker.asyncio,'sleep',new=AsyncMock()):
            result=asyncio.run(worker.collect(dict(platform='bili',limit=60,pages=5)))
        self.assertEqual(page.await_count,3);self.assertEqual(len(result['documents']),2)
        self.assertEqual(result['state'],'needs-human')


if __name__=='__main__': unittest.main()
