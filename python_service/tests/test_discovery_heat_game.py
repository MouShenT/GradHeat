import json
import math
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'crawler'))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools/research'))
from gradheat_core.admissions_decision import publication_version
from gradheat_core.dashboard import DiscoveryInput, discover, programme_overview
from gradheat_core.congestion import ScenarioInput, ScenarioOption, solve, simulate
from gradheat_core.heat import summarize
from gradheat_python.heat import HeatReader
from test_admissions_decision import programme


class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.payload = dict(data_as_of='2026-10-09', programmes=[
            programme(1, group='985'), programme(2, group='研究所'),
            programme(3, eligible_11408=False, group='985'),
            programme(4, year=2026, group='985'),
            programme(5, mode='非全日制', group='985')], history=[])

    def request(self, **changes):
        return DiscoveryInput(data_version=publication_version(self.payload), **changes)

    def test_no_score_required_unknown_background_does_not_award_points(self):
        overview = programme_overview(self.payload, self.root)
        result = discover(self.payload, overview, self.request())
        self.assertEqual(result['eligible_candidates'], 2)
        self.assertEqual({p['preference_score'] for p in result['ranking']}, {8.5})
        self.assertTrue(all(p['background']['friendliness']=='unknown' for p in result['ranking']))
        self.assertNotIn('exam_score', json.dumps(result))
        self.assertNotIn('probability', json.dumps(result))
        self.assertIsNone(overview['programmes'][0]['ordinary_quota'])

    def test_user_group_preference_changes_order_but_unverified_rules_filter_cannot_pass(self):
        overview = programme_overview(self.payload, self.root)
        result = discover(self.payload, overview, self.request(group_weights={'研究所':10, '985':0}))
        self.assertEqual(result['ranking'][0]['group'], '研究所')
        self.assertEqual(discover(self.payload, overview, self.request(background_filter='related-rules'))['ranking'], [])
        with self.assertRaises(ValueError):
            discover(self.payload, overview, self.request(group_weights={'未经核对的A+层次':10}))

    def test_multiple_plan_versions_and_other_major_history_are_not_chart_values(self):
        self.payload['programmes'][0]['plan_variants']=['25','30']
        self.payload['history']=[dict(id='other',unit='样本大学',year=2026,department='计算机学院',major_name='软件工程',cutoff=999)]
        result = programme_overview(self.payload, self.root)
        self.assertIsNone(result['programmes'][0]['reported_plan'])
        self.assertEqual(result['programmes'][0]['history'], [])

    def test_direction_can_identify_electronic_information_subject(self):
        self.payload['programmes']=[programme(1, group='研究所', major_code='085400', major_name='电子信息', directions=['03计算机技术'])]
        result=discover(self.payload,programme_overview(self.payload,self.root),self.request(majors=['计算机']))
        self.assertEqual(result['eligible_candidates'],1)

    def test_invalid_preferences(self):
        for changes in (dict(major_weight=0,group_weight=0), dict(majors=['未知']),dict(group_weights={'985':float('nan')})):
            with self.assertRaises(ValidationError):self.request(**changes)


class CongestionTests(unittest.TestCase):
    def options(self, capacities=(20,20), preferences=(5,5)):
        return [ScenarioOption(programme_id=str(i),capacity=c,preference=p) for i,(c,p) in enumerate(zip(capacities,preferences))]

    def test_equal_preferences_balance_equal_capacities(self):
        result=solve(self.options(),120,2)
        self.assertTrue(result['converged'])
        self.assertEqual([p['hypothetical_choices'] for p in result['allocations']],[60,60])
        self.assertEqual(result['maximum_improvement'],0)

    def test_equilibrium_has_no_improving_deviation_and_potential_never_increases(self):
        for seed in range(12):
            options=self.options((12,30,55),(4,6,5))
            result=solve(options,119,2,seed)
            counts=[r['hypothetical_choices'] for r in result['allocations']]
            self.assertEqual(sum(counts),119)
            self.assertTrue(result['converged'])
            self.assertLessEqual(result['potential_final'],result['potential_initial']+1e-8)
            for a,number in enumerate(counts):
                if not number:continue
                current=options[a].preference-2*number/options[a].capacity
                for b,o in enumerate(options):
                    if b!=a:self.assertLessEqual(o.preference-2*(counts[b]+1)/o.capacity,current+1e-9)

    def test_single_move_potential_difference_equals_negative_utility_gain(self):
        # Independently check the exact-potential identity for arbitrary feasible moves.
        options=self.options((7,31),(4,8));weight=2.3
        def phi(n):return sum(weight*x*(x+1)/(2*o.capacity)-x*o.preference for x,o in zip(n,options))
        for n in [(1,9),(3,7),(10,0)]:
            before=options[0].preference-weight*n[0]/options[0].capacity
            after=options[1].preference-weight*(n[1]+1)/options[1].capacity
            self.assertAlmostEqual(phi([n[0]-1,n[1]+1])-phi(n),before-after,places=11)

    def test_budget_and_seed_are_honest_and_deterministic(self):
        options=self.options((1,100),(0,10))
        limited=solve(options,120,2,move_budget=1)
        self.assertFalse(limited['converged']);self.assertEqual(limited['moves'],1)
        self.assertGreater(limited['maximum_improvement'],0)
        request=ScenarioInput(options=options)
        a,b=simulate(request),simulate(request)
        self.assertEqual(a,b);self.assertIsNone(a['admission_probability'])
        self.assertEqual([r['participants'] for r in a['sensitivity']],[90,120,150])

    def test_capacity_and_duplicate_validation(self):
        for changes in (dict(capacity=0),dict(preference=float('inf'))):
            with self.assertRaises(ValidationError):ScenarioOption(**(dict(programme_id='a',capacity=1,preference=5)|changes))
        with self.assertRaises(ValidationError):ScenarioInput(options=self.options()+[self.options()[0]])


class HeatTests(unittest.TestCase):
    def test_deduplication_known_zero_and_unknown_are_distinct(self):
        docs=[dict(platform='xhs',content_id='a',query='样本大学 考研',query_sort='latest',observed_at='2026-10-08',metrics={'liked_count':99}),
            dict(platform='xhs',content_id='a',query='样本大学 408',query_sort='general',observed_at='2026-10-09',metrics={'liked_count':0}),
            dict(platform='xhs',content_id='b',query='样本大学 考研',query_sort='latest',observed_at='2026-10-09',metrics={}),
            dict(platform='xhs',content_id='other',query='另一所大学 考研',observed_at='2026-10-09',metrics={'liked_count':123}),
            dict(platform='dy',content_id='d',query='样本大学 考研',observed_at='2026-10-09',metrics={'play_count':0})]
        result=summarize(docs,'样本大学',{},'2026-10-09');xhs,zhihu,dy,bili=result['platforms']
        self.assertEqual(xhs['unique_contents'],2)
        self.assertEqual(xhs['metrics']['like'],dict(sum_known_values=0,known_contents=1,unknown_contents=1))
        self.assertEqual(len(xhs['query_groups']),2)
        self.assertIsNone(dy['metrics']['view']['sum_known_values'])
        self.assertEqual(bili['sampling_state'],'no-stored-sample');self.assertIsNone(bili['metrics']['view']['sum_known_values'])
        self.assertIsNone(result['trend']);self.assertIsNone(result['applicant_count'])

    def test_failed_refresh_uses_old_time_and_missing_is_not_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=HeatReader(type("FailedDatabase",(),{"connect":lambda self: (_ for _ in ()).throw(TimeoutError("private details"))})());data=summarize([],'样本大学',{},'old-checked-at')
            store.cache['样本大学']=(-math.inf,data)
            with patch('gradheat.vm_db.connect_vm',side_effect=TimeoutError('private details')):
                result=store.read('样本大学');missing=store.read('无样本大学')
            self.assertEqual(result['checked_at'],'old-checked-at')
            self.assertEqual(result['read_state'],'using-last-verified-cache')
            self.assertNotIn('private details',json.dumps(result))
            self.assertEqual(missing['read_state'],'unavailable');self.assertEqual(missing['platforms'],[])




if __name__=='__main__':unittest.main()
