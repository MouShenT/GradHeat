import copy
import hashlib
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'python_service'))
from gradheat_core.decision_inputs import net_quota, resolve_inputs
from gradheat_core.intelligence import heat_index, PersonalProfile, VictoryInput, victory_indices
from gradheat_core.market_game import equilibrium
from gradheat_python.school_facts import AdmissionValues, import_facts
from pydantic import ValidationError


def programme(name='甲', **fields):
    return dict(id=name,unit=name,major_code='081200',major_name='计算机科学与技术',department='计算机学院',
                year=2027,mode='全日制',eligible_11408=True,**fields)


def fact(**fields):
    return dict(unit='甲',year=2026,department='计算机学院',major_code='081200',mode='全日制',
                route='first-choice',population='ordinary',source_url='https://example.org/a',observed_at='2026-03-20',**fields)


class InputResolutionTests(unittest.TestCase):
    def test_only_unambiguous_net_plans_are_capacities(self):
        self.assertEqual(net_quota(dict(plan_text='专业：40(不含推免)'))[0],40)
        for raw in ['专业：40(含推免)','40','专业：40(不含推免)；研究方向：10(不含推免)']:
            self.assertIsNone(net_quota(dict(plan_text=raw))[0])
        self.assertIsNone(net_quota(dict(plan_text='专业：40(不含推免)',plan_variants=['专业：40(不含推免)','专业：41(不含推免)']))[0])
        self.assertIsNone(net_quota(dict(plan_text='研究方向：10(不含推免)',directions=['一','二']))[0])
        self.assertIsNone(net_quota(dict(plan_text='专业：40(不含推免)',verification={'plan_text':{'state':'conflict'}}))[0])

    def test_wrong_department_route_special_and_future_are_excluded(self):
        p=programme();other=dict(p,id='p2',department='教育学院')
        facts=[fact(values={'cutoff':330,'ordinary_quota':20}),
               dict(fact(values={'cutoff':490}),department='教育学院',source_url='https://example.org/b'),
               dict(fact(values={'cutoff':200}),route='transfer'),
               dict(fact(values={'cutoff':210}),special=True),
               dict(fact(values={'cutoff':480}),year=2028),
               dict(fact(values={'ordinary_quota':1000}),year=2023)]
        result=resolve_inputs(p,dict(programmes=[p,other],decision_facts=facts),[])
        self.assertEqual(result['threshold'],330);self.assertEqual(result['capacity_proxy'],20)
        self.assertIsNone(result['ordinary_quota']);self.assertEqual(result['capacity_year'],2026)

    def test_renamed_department_requires_unique_programme_scope(self):
        p=programme();f=dict(fact(values={'cutoff':340}),department='新计算机学院')
        self.assertEqual(resolve_inputs(p,dict(programmes=[p],decision_facts=[f]),[])['threshold'],340)
        self.assertIsNone(resolve_inputs(p,dict(programmes=[p,dict(p,id='b',department='教育学院')],decision_facts=[f]),[])['threshold'])

    def test_zero_quota_conflicting_quota_and_sample_counts(self):
        p=programme(ordinary_quota=30)
        f=dict(fact(values={'ordinary_quota':0}),year=2027)
        self.assertEqual(resolve_inputs(p,dict(decision_facts=[f]),[])['ordinary_quota'],0)
        conflict=dict(f,source_url='https://example.org/b',values={'ordinary_quota':20})
        self.assertIsNone(resolve_inputs(p,dict(decision_facts=[f,conflict]),[])['ordinary_quota'])
        sample=dict(f,population='observed-sample',values={'admitted_count':17})
        self.assertIsNone(resolve_inputs(programme(),dict(decision_facts=[sample]),[])['capacity_proxy'])

    def test_current_rules_keep_year_and_same_subjects_do_not_signal_change(self):
        f=dict(fact(values={'equivalent_education_allowed':False,'score_limits':{'english':55}}),year=2027)
        r=resolve_inputs(programme(),dict(decision_facts=[f]),[dict(year=2026,cutoff=320,exam_text='101政治 201英语一 301数学一 408')])
        self.assertFalse(r['subject_change']);self.assertEqual(r['score_limits_year'],2027)
        self.assertEqual(r['restriction_years']['equivalent_education_allowed'],2027)


class HeatWindowTests(unittest.TestCase):
    def signal(self, **changes):
        return dict(dict(kind='search-index',provider='synthetic',keyword='甲大学研究生',value=200,reference_scale=1000,
                    source_url='https://example.org/index',window_start='2026-09-26',window_end='2026-10-09'),**changes)

    def test_overlapping_runs_and_total_devices_do_not_inflate_search(self):
        s=self.signal();old=dict(s,window_start='2026-09-01',window_end='2026-09-30',value=999)
        both=[s,dict(s,device='pc',value=80),dict(s,device='wise',value=120),old]
        self.assertEqual(heat_index([],both,'2026-10-10')['heat_value'],heat_index([],[s],'2026-10-10')['heat_value'])
        self.assertEqual(heat_index([],both,'2026-10-10')['search_observations'],1)

    def test_momentum_requires_observed_days_and_known_zero_stays_zero(self):
        s=self.signal(daily=[dict(date=f'2026-09-{d}',value=20) for d in range(26,31)]+
                           [dict(date=f'2026-10-{d:02}',value=20 if d<3 else 80) for d in range(1,10)])
        rising=heat_index([],[s],'2026-10-10');self.assertGreater(rising['search_momentum'],0)
        self.assertGreater(rising['heat_value'],heat_index([],[self.signal()],'2026-10-10')['heat_value'])
        s['daily']=[dict(date='2026-10-09',value=80)]
        self.assertIsNone(heat_index([],[s],'2026-10-10')['search_momentum'])
        self.assertEqual(heat_index([],[self.signal(value=0)],'2026-10-10')['heat_value'],0)

    def test_freshness_and_missing_observations(self):
        s=self.signal();self.assertGreater(heat_index([],[s],'2026-10-10')['heat_value'],heat_index([],[s],'2026-11-10')['heat_value'])
        for invalid in [dict(s,coverage=0),dict(s,value=None),dict(s,window_start='2026-10-10'),dict(s,kind='search-result-count')]:
            self.assertIsNone(heat_index([],[invalid],'2026-10-10')['heat_value'])


class GameTests(unittest.TestCase):
    def test_mass_stationarity_symmetry_and_capacity_response(self):
        base=[dict(id='a',capacity=20,attraction=1),dict(id='b',capacity=20,attraction=1)]
        r=equilibrium(base);self.assertAlmostEqual(sum(r['shares'].values()),1,10)
        self.assertAlmostEqual(r['shares']['a'],.5,9);self.assertLess(r['residual'],1e-7)
        expanded=equilibrium([base[0],dict(base[1],capacity=60)])
        self.assertLess(expanded['pressure']['b'],expanded['pressure']['a'])
        self.assertGreater(expanded['shares']['b'],expanded['shares']['a'])
        self.assertEqual(r,equilibrium(base));self.assertIsNone(r['real_applicants'])
        self.assertEqual(equilibrium([])['shares'],{})

    def test_invalid_or_duplicate_market_options_rejected(self):
        for opts in [[dict(id='a',capacity=0,attraction=1)],
                     [dict(id='a',capacity=20,attraction=float('inf'))],
                     [dict(id='a',capacity=20,attraction=1)]*2]:
            with self.assertRaises(ValueError):equilibrium(opts)

    def fixture(self):
        ps=[programme(n,ordinary_quota=40) for n in ['甲','乙']]
        hs=[dict(id=n,year=2026,cutoff=320) for n in ['甲','乙']]
        payload=dict(programmes=ps,history=hs,historical_alignment={n:dict(matched=[n]) for n in ['甲','乙']})
        dossiers={n:dict(programmes=[p],heat=dict(heat_value=h)) for n,p,h in zip(['甲','乙'],ps,[20,80])}
        return payload,dossiers

    def run_indices(self,payload,dossiers,**profile):
        return victory_indices(payload,dossiers,VictoryInput(data_version='a'*64,profile=PersonalProfile(score=350,**profile)))

    def test_preferences_and_limit_do_not_rebuild_market(self):
        p,d=self.fixture();all_rows=self.run_indices(p,d)['ranking'];one=self.run_indices(p,d,preferred_units=['乙'])['ranking'][0]
        self.assertEqual(one,next(x for x in all_rows if x['unit']=='乙'))
        duplicated=copy.deepcopy(p);duplicated['programmes'].append(dict(p['programmes'][0],id='甲2'))
        duplicated['historical_alignment']['甲2']=dict(matched=['甲'])
        self.assertEqual(self.run_indices(p,d)['game_options'],self.run_indices(duplicated,d)['game_options'])
        self.assertEqual(self.run_indices(p,d)['ranking'][0]['crowding_pressure'],self.run_indices(duplicated,d)['ranking'][0]['crowding_pressure'])

    def test_risk_aversion_and_single_subject_rules(self):
        p,d=self.fixture();bold=self.run_indices(p,d,risk_aversion=0)['ranking'][0];safe=self.run_indices(p,d,risk_aversion=1)['ranking'][0]
        self.assertGreater(bold['victory_index'],safe['victory_index']);self.assertEqual(safe['victory_index'],safe['robust_index'])
        d['甲']['decision_facts']=[fact(values={'score_limits':{'english':60},'cutoff':320})]
        reduced=self.run_indices(p,d,english=50)['ranking'];row=next(x for x in reduced if x['unit']=='甲')
        self.assertLess(row['victory_index'],safe['victory_index']);self.assertGreater(row['victory_index'],0)
        d['甲']['decision_facts'].append(dict(fact(values={'equivalent_education_allowed':False}),year=2027))
        row=next(x for x in self.run_indices(p,d,equivalent_education=True)['ranking'] if x['unit']=='甲')
        self.assertEqual(row['victory_index'],0);self.assertEqual(row['current_rule_failures'],['equivalent_education_allowed'])

    def test_heat_coverage_changes_confidence_and_background_is_scoped(self):
        p,d=self.fixture()
        d['甲']['heat']['confidence_index']=20
        d['甲']['claims']=[dict(field='background_note',year=2026,scope='081200 数学跨考接受',origin='synthetic')]
        low=next(x for x in self.run_indices(p,d,undergraduate_major='数学')['ranking'] if x['unit']=='甲')
        d['甲']['heat']['confidence_index']=90
        high=next(x for x in self.run_indices(p,d,undergraduate_major='数学')['ranking'] if x['unit']=='甲')
        self.assertGreater(high['confidence_index'],low['confidence_index'])
        self.assertEqual(high['victory_index'],low['victory_index'])
        absent=next(x for x in self.run_indices(p,d,undergraduate_major='物理')['ranking'] if x['unit']=='甲')
        self.assertEqual(high['background_evidence_count'],1);self.assertEqual(absent['background_evidence_count'],0)
        self.assertGreater(high['victory_index'],absent['victory_index'])

    def test_historical_diagnostic_holds_out_latest_cutoff(self):
        sys.path.insert(0,str(ROOT/'tools/research'))
        from evaluate_index_models import evaluate
        p,d=self.fixture()
        for n in ['甲','乙']:
            p['history'].append(dict(id=n+'old',year=2025,cutoff=300))
            p['historical_alignment'][n]['matched'].append(n+'old')
        result=evaluate(p,d)
        self.assertEqual(result['historical_diagnostic']['latest_cutoff_mae'],20)
        self.assertFalse(result['historical_diagnostic']['probability_calibrated'])


class FactValidationTests(unittest.TestCase):
    def test_bounds_and_populations_do_not_hide_invalid_values(self):
        for raw in [dict(cutoff=999),dict(admitted_minimum=350,admitted_mean=340),dict(initial_weight=.6,interview_weight=.6),dict(score_limits={'english':101}),{},dict(cutoff=float('nan'))]:
            with self.assertRaises(ValidationError):AdmissionValues.model_validate(raw)
        self.assertEqual(AdmissionValues(ordinary_quota=0).ordinary_quota,0)

    def test_batch_validated_before_any_database_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'original.html';source.write_bytes(b'public synthetic source')
            item=dict(fact(values={'cutoff':330}),major_name='计算机',source_artifact=str(source),
                      source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),locator='table[0] row[1]')
            invalid=dict(item,source_sha256='0'*64)
            con=Mock()
            with self.assertRaises(ValueError):import_facts(con,root,[item,invalid],['甲'])
            con.cursor.assert_not_called()


if __name__=='__main__':unittest.main()
