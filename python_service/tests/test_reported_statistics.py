import hashlib
import unittest
from unittest.mock import MagicMock

from pydantic import ValidationError

from gradheat_core.decision_inputs import resolve_inputs
from gradheat_core.intelligence import canonical
from gradheat_python.intelligence import DossierReader
from gradheat_python.school_facts import ReportedStatistics, SchoolFact


class ReportedStatisticsTests(unittest.TestCase):
    def fact(self, **changes):
        return dict(dict(unit='甲校', year=2026, department='计算机学院', major_code='081200',
            major_name='计算机', population='reported-aggregate', observed_at='2026-09-29',
            source_url='https://school.example.edu/statistics.pdf', source_artifact='synthetic.pdf',
            source_sha256='b'*64, locator='table 1',
            values={'reported_statistics': {'applicants':120, 'admitted_total':30,
                'recommended_exemption':5, 'first_choice_admitted':20, 'transfer_admitted':5,
                'includes_special':True}}), **changes)

    def test_missing_counts_remain_missing_and_explicit_zero_is_retained(self):
        result=ReportedStatistics(applicants=120, transfer_admitted=0).model_dump(exclude_none=True)
        self.assertEqual(result, {'applicants':120, 'transfer_admitted':0})
        for values in ({}, {'includes_special':True}, {'applicants':True}, {'applicants':-1},
                       {'admitted_total':10, 'first_choice_admitted':11},
                       {'admitted_minimum':350, 'admitted_mean':320}):
            with self.subTest(values=values), self.assertRaises(ValidationError):
                ReportedStatistics.model_validate(values)

    def test_aggregate_statistics_cannot_be_labelled_ordinary_or_attached_to_quota(self):
        self.assertEqual(SchoolFact.model_validate(self.fact()).values.reported_statistics.admitted_total,30)
        for fact in (self.fact(population='ordinary'),
                     self.fact(values={'ordinary_quota':30,'reported_statistics':{'admitted_total':30}}),
                     self.fact(values={'reported_statistics':{'admitted_mean':330},'admitted_mean':330}),
                     self.fact(values={'admitted_count':30})):
            with self.subTest(fact=fact), self.assertRaises(ValidationError):
                SchoolFact.model_validate(fact)

    def test_aggregate_cannot_change_threshold_capacity_or_retest_ratio(self):
        p=dict(id='p',unit='甲校',year=2027,department='计算机学院',major_code='081200',mode='全日制')
        # Also defend the resolver against a malformed legacy record that bypassed validation.
        aggregate=self.fact(route='first-choice',mode='全日制', values={'ordinary_quota':999,
            'cutoff':450,'interview_count':1000,'admitted_mean':440,'score_limits':{'english':99}})
        baseline=resolve_inputs(p,{'programmes':[p]},[])
        self.assertEqual(resolve_inputs(p,{'programmes':[p],'decision_facts':[aggregate]},[]),baseline)

    def test_public_statistics_retain_scope_and_public_link_without_private_provenance(self):
        fact=SchoolFact.model_validate(self.fact()).model_dump(exclude_none=True)
        dossier=dict(unit='甲校',admissions_version='a'*64,tier='普通院校',counts={},heat={},
            programmes=[],history=[],claims=[],decision_facts=[fact])
        body=canonical(dossier).encode();sha=hashlib.sha256(body).hexdigest()
        db=MagicMock();cursor=db.connect.return_value.__enter__.return_value.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value=(sha,body)
        result=DossierReader(db).public('甲校','a'*64)['decision_facts'][0]
        self.assertEqual(result['population'],'reported-aggregate')
        self.assertTrue(result['values']['reported_statistics']['includes_special'])
        self.assertEqual(result['url'],fact['source_url'])
        for private in ('source_url','source_artifact','source_sha256'):
            self.assertNotIn(private,canonical(result))


if __name__=='__main__':
    unittest.main()
