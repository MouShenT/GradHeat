import hashlib,json,unittest
from unittest.mock import MagicMock

from gradheat_core.intelligence import canonical,VictoryInput,victory_indices
from gradheat_python.intelligence import DossierReader


class DossierReaderTests(unittest.TestCase):
    def fixture(self):
        p=dict(id='p',unit='甲校',year=2027,eligible_11408=True,mode='全日制',major_code='081200',major_name='计算机',group='211',ordinary_quota=30)
        d=dict(unit='甲校',admissions_version='a'*64,observed_at='2026-10-13',tier='211',heat=dict(heat_value=35),programmes=[p],history=[],counts={},claims=[],decision_facts=[],community_sources=[],contents=[dict(text='large original text')],official_materials=[])
        body=canonical(d).encode();sha=hashlib.sha256(body).hexdigest()
        db=MagicMock();con=db.connect.return_value.__enter__.return_value;cur=con.cursor.return_value.__enter__.return_value
        return p,d,body,sha,db,cur

    def test_official_reference_uses_public_link_contract_without_raw_provenance(self):
        p,d,body,sha,db,cur=self.fixture()
        d['decision_facts']=[dict(year=2026,department='计算机学院',major_code='081200',major_name='计算机',mode='全日制',
            route='first-choice',population='ordinary',values=dict(cutoff=310),campus='乙校区',cutoff_kind='school-minimum',
            excerpt='校级最低要求，院系可另定要求',source_url='https://school.example.edu/rules.pdf',
            source_artifact='D:/private/synthetic-original.pdf',source_sha256='b'*64)]
        body=canonical(d).encode();sha=hashlib.sha256(body).hexdigest();cur.fetchone.return_value=(sha,body)
        result=DossierReader(db).public('甲校','a'*64);reference=result['decision_facts'][0]
        self.assertEqual(reference['url'],'https://school.example.edu/rules.pdf')
        self.assertEqual(reference['campus'],'乙校区')
        self.assertEqual(reference['cutoff_kind'],'school-minimum')
        for key in ('source_url','source_artifact','source_sha256'):
            self.assertNotIn(key,canonical(result))
        self.assertNotIn('D:/private',canonical(result))

    def test_single_school_reads_only_requested_original_and_rejects_corruption(self):
        p,d,body,sha,db,cur=self.fixture();cur.fetchone.return_value=(sha,body)
        reader=DossierReader(db);result=reader.public('甲校','a'*64)
        self.assertTrue(result['available']);self.assertEqual(result['dossier_version'],sha)
        self.assertEqual(cur.execute.call_args.args[1],('甲校','a'*64))
        self.assertIn('v.unit=%s',cur.execute.call_args.args[0]);cur.fetchall.assert_not_called()
        cur.fetchone.return_value=(sha,body+b' ')
        with self.assertRaises(ValueError):reader.public('甲校','a'*64)

    def test_admission_samples_publish_only_summary_scalars_and_keep_algorithm_missing(self):
        p,d,body,sha,db,cur=self.fixture()
        sample=dict(program_name='计算机技术',year=2026,exam_text='11408',record_count=3,
            admitted_sample_count=2,unadmitted_retest_sample_count=1,observed_retest_list_minimum=310,
            admitted_total_minimum=330,distribution_population='observed-records',verification_state='source-reported-sample')
        private=dict(identifiers=['synthetic-identifier'],subjects=[{'name':'private raw subject'}],
            source_artifact='D:/private/synthetic-original.json',raw={'private':'arbitrary original JSON'},
            cutoff=310,ordinary_quota=2,elimination_rate=1/3)
        d['community_sources']=[dict(unit='甲校',site_url='https://example.org/school',score_url='https://example.org/stats',
            observed_at='2026-10-18',pages=[],scores=[],gaps=[],admission_samples=[sample|private],**private)]
        body=canonical(d).encode();sha=hashlib.sha256(body).hexdigest();cur.fetchone.return_value=(sha,body)
        result=DossierReader(db).public('甲校','a'*64);source=result['community_sources'][0]
        self.assertEqual(source['admission_samples'],[sample])
        self.assertEqual(source['scores'],[]);self.assertEqual(source['source_type'],'community')
        public=canonical(source)
        for forbidden in ('identifiers','synthetic-identifier','subjects','source_artifact','D:/private','arbitrary original JSON','ordinary_quota','elimination_rate','cutoff'):
            self.assertNotIn(forbidden,public)
        from gradheat_core.decision_inputs import resolve_inputs
        inputs=resolve_inputs(p,d,[])
        self.assertIsNone(inputs['threshold'])
        self.assertEqual(inputs['ordinary_quota'],30)

    def test_admission_sample_scalar_columns_cannot_carry_nested_raw_data(self):
        p,d,body,sha,db,cur=self.fixture()
        source=dict(unit='甲校',site_url='https://example.org/school',score_url='https://example.org/stats',
            observed_at='2026-10-18',pages=[],scores=[],gaps=[])
        cases=[({},[]),({'admission_samples':{'raw':'private'}},[]),
            ({'admission_samples':[{'program_name':{'raw':'private'},'year':True,
                'record_count':['private identifier'],'observed_retest_list_minimum':{'raw':'private'}},'raw JSON']},[]),
            ({'admission_samples':[{'program_name':'计算机技术','record_count':0,'admitted_total_minimum':None,'ordinary_quota':999}]},
                [{'program_name':'计算机技术','record_count':0,'admitted_total_minimum':None}])]
        for extra,expected in cases:
            with self.subTest(extra=extra):
                d['community_sources']=[source|extra]
                body=canonical(d).encode();sha=hashlib.sha256(body).hexdigest();cur.fetchone.return_value=(sha,body)
                result=DossierReader(db).public('甲校','a'*64)
                self.assertEqual(result['community_sources'][0]['admission_samples'],expected)

    def test_compact_inputs_preserve_algorithm_results_and_verify_source_identity(self):
        p,d,body,sha,db,cur=self.fixture()
        fields=('unit','admissions_version','observed_at','tier','heat','programmes','claims','decision_facts','community_sources')
        projection=json.dumps([d[k] for k in fields]);cur.fetchall.return_value=[('甲校',sha,sha,projection)]
        reader=DossierReader(db);compact=reader.all('a'*64)
        self.assertNotIn('contents',compact['甲校']);self.assertNotIn('official_materials',compact['甲校'])
        payload=dict(target_year=2027,programmes=[p],history=[dict(id='h',year=2026,cutoff=320)],historical_alignment={'p':dict(matched=['h'])})
        request=VictoryInput(data_version='a'*64,profile=dict(score=350))
        self.assertEqual(victory_indices(payload,{'甲校':d},request),victory_indices(payload,compact,request))
        cur.fetchall.return_value=[('甲校',sha,'b'*64,projection)]
        with self.assertRaises(ValueError):DossierReader(db).all('a'*64)
        wrong=dict(d,unit='乙校');cur.fetchall.return_value=[('甲校',sha,sha,json.dumps([wrong[k] for k in fields]))]
        with self.assertRaises(ValueError):DossierReader(db).all('a'*64)

    def test_older_dossier_missing_optional_fields_falls_back_to_its_own_original(self):
        p,d,body,sha,db,cur=self.fixture();d.pop('community_sources')
        body=canonical(d).encode();sha=hashlib.sha256(body).hexdigest()
        cur.fetchall.return_value=[('甲校',sha,sha,json.dumps(['甲校','a'*64]))]
        cur.fetchone.return_value=(body,)
        result=DossierReader(db).all('a'*64)['甲校']
        self.assertEqual(result['heat'],d['heat']);self.assertEqual(result['programmes'],d['programmes'])
        self.assertNotIn('contents',result);self.assertNotIn('community_sources',result)
        self.assertEqual(cur.execute.call_args.args[1],('甲校',sha))
