import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from gradheat_core.corroboration import Corroborator, scope, digest, origin


class InformationMatchTests(unittest.TestCase):
    def obs(self, provider, row, field, value, kind='history', official=False):
        key = scope(row, kind)
        item = dict(scope=key, scope_id=digest(key), field=field, value=value,
            raw_value=value, origin_id=provider, official=official)
        item['id'] = digest(item)
        return item

    def base(self, **changes):
        return dict(unit='样本大学', year=2026, department='计算机学院', major_name='人工智能') | changes

    def test_same_information_across_three_formats_and_table_types(self):
        official = self.base(department=None, major_name=None, label='报考专业：人工智能；专业代码：0812Z3')
        table = self.base(department='(003)计算机学院', major_name='0812Z3人工智能')
        distribution = self.base(department=None, major_name=None, scope='计算机学院 人工智能（学硕）', population='retest_pool')
        checker = Corroborator([
            self.obs('school', official, 'cutoff', '330', 'line', True),
            self.obs('institution-a', table, 'cutoff_text', '330、45、85'),
            self.obs('institution-b', distribution, 'cutoff', '330.0', 'distribution')])
        verdict, record = checker.decision(table, 'history', 'cutoff_text', '330、45、85')
        self.assertEqual(verdict['state'], 'three-source-agreement')
        self.assertEqual(verdict['official_state'], 'matched')
        self.assertEqual(record['parts'][0]['value'], '330')
        self.assertEqual(len(record['observation_ids']), 3)

    def test_ambiguous_missing_college_does_not_borrow_both_colleges(self):
        query = self.base(department=None)
        checker = Corroborator([self.obs('a', query, 'cutoff_text', '330'),
            self.obs('b', self.base(department='第一学院'), 'cutoff_text', '330'),
            self.obs('c', self.base(department='第二学院'), 'cutoff_text', '330')])
        verdict, record = checker.decision(query, 'history', 'cutoff_text', '330')
        self.assertEqual(verdict['agreeing_sources'], 1)
        self.assertIn('department', record['parts'][0]['ambiguous_facets'])

    def test_codes_modes_years_and_special_plans_stay_separate(self):
        query = self.base(major_code='0812Z3', mode='全日制')
        rows = [self.obs('a', query, 'cutoff_text', '330')]
        for provider, changed in [('b', {'major_code': '085410'}), ('c', {'mode': '非全日制'}),
            ('d', {'year': 2025}), ('e', {'special_scope': '退役士兵'})]:
            rows.append(self.obs(provider, query | changed, 'cutoff_text', '330'))
        self.assertEqual(Corroborator(rows).decision(query, 'history', 'cutoff_text', '330')[0]['agreeing_sources'], 1)

    def test_minimum_observed_score_is_not_retest_cutoff(self):
        row = self.base()
        checker = Corroborator([self.obs('a', row, 'cutoff_text', '最低分330'),
            self.obs('b', row, 'cutoff_text', '330'), self.obs('c', row, 'cutoff_text', '330')])
        self.assertEqual(checker.decision(row, 'history', 'cutoff_text', '330')[0]['agreeing_sources'], 2)

    def test_separate_exam_cannot_become_ordinary_official_conflict(self):
        ordinary = self.base(major_name='电子信息-软件方向', major_code='085405', mode='非全日制')
        separate = self.base(major_name='软件工程（单独考试）', major_code='085405', mode='非全日制')
        checker = Corroborator([self.obs('a', ordinary, 'cutoff_text', '272'),
            self.obs('official', separate, 'cutoff', '264', official=True)])
        verdict, _ = checker.decision(ordinary, 'history', 'cutoff_text', '272')
        self.assertEqual(verdict['state'], 'pending')
        self.assertNotEqual(verdict['official_state'], 'conflict')

    def test_summary_and_distribution_match_same_stats_with_stated_precision(self):
        row = self.base(population='enrolled')
        observations = [self.obs('a', row, 'admitted_score_text', '362【321-418】'),
            self.obs('b', row, 'admitted_score_text', '均分362；范围321–418')]
        observations += [self.obs('c', row, field, number, 'distribution') for field, number in
            [('mean', 361.54), ('minimum', 321), ('maximum', 418)]]
        verdict, _ = Corroborator(observations).decision(row, 'history', 'admitted_score_text', '362【321-418】')
        self.assertEqual(verdict['state'], 'three-source-agreement')
        # Retest entrants and admitted students describe different populations.
        checker = Corroborator(observations[:2] + [self.obs('c', row | {'population': 'retest_pool'}, 'mean', 361.54, 'distribution')])
        self.assertEqual(checker.decision(row, 'history', 'admitted_score_text', '362【321-418】')[0]['state'], 'two-source-agreement')
        self.assertEqual(checker.decision(row, 'history', 'admitted_score_text', '362【321-418】')[0]['agreeing_sources'], 2)

    def test_rounded_mean_does_not_count_as_an_additional_information_item(self):
        row=self.base(population='enrolled')
        checker=Corroborator([self.obs('a',row,'admitted_score_text','362【321-418】')]+[
            self.obs('b',row,f,v,'distribution') for f,v in [('mean',361.54),('minimum',321),('maximum',418)]])
        items=checker.information_agreements(checker.decisions())
        self.assertEqual(len(items),3)
        self.assertEqual([x['value'] for x in items if x['metric']=='admitted_mean'],['361.54'])

    def test_plan_exemption_and_extent_distinguish_meanings(self):
        row = self.base()
        checker = Corroborator([self.obs('a', row, 'plan_text', '专业：25(不含推免)', 'programme'),
            self.obs('b', row, 'plan_text', '专业25人，不含推免', 'programme'),
            self.obs('c', row, 'plan_text', '25人(不含推免)', 'programme')])
        self.assertEqual(checker.decision(row, 'programme', 'plan_text', '专业：25(不含推免)')[0]['state'], 'three-source-agreement')
        conflicting = Corroborator(checker.rows[:2] + [self.obs('c', row, 'plan_text', '专业25(含推免)', 'programme')])
        self.assertEqual(conflicting.decision(row, 'programme', 'plan_text', '专业：25(不含推免)')[0]['agreeing_sources'], 2)

    def test_exam_shorthand_and_full_subject_codes_are_same_information(self):
        row = self.base()
        checker = Corroborator([self.obs('a', row, 'exam_text', '11408'),
            self.obs('b', row, 'subjects', ['101', '201', '301', '408'], 'programme'),
            self.obs('c', row, 'exam_text', '101政治、201英语一、301数学一、408计算机')])
        self.assertEqual(checker.decision(row, 'history', 'exam_text', '11408')[0]['state'], 'three-source-agreement')
        self.assertIsNone(scope(row | {'year': None}, 'history'))

    def test_repo_attributed_to_institution_cannot_be_extra_source(self):
        row=dict(repository='example/repo',source_family='example/repo',raw={'src':['N诺','三源核对']})
        self.assertEqual(origin(row),'noobdream')

    def test_official_department_and_no_direction_wording_are_recognized(self):
        row=self.base(department=None,major_name=None,label='学院代码及名称：005计算机学院；专业代码：0812Z3；专业名称：人工智能；研究方向：不区分方向')
        key=scope(row,'line')
        self.assertEqual(key['department'],'计算机学院')
        self.assertEqual(key['directions'],[])

    def test_reviewed_direction_quotas_cannot_borrow_another_direction(self):
        base=self.base(major_name='电子信息',major_code='085400')
        one=base|{'consensus_directions':['01']}
        two=base|{'consensus_directions':['02']}
        checker=Corroborator([self.obs('school',one,'plan_text','方向：17（不含推免）','programme',True),
            self.obs('agency',two,'plan_text','方向：17（不含推免）','programme')])
        verdict,_=checker.decision(one,'programme','plan_text','方向：17（不含推免）')
        self.assertEqual(verdict['state'],'pending')
        self.assertEqual(verdict['agreeing_sources'],1)


if __name__ == '__main__':
    unittest.main()
