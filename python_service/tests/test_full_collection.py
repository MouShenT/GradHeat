import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'tools/research'))
import run_full_social_collection as full
from social_evidence import digest, encode


class FullCollectionTests(unittest.TestCase):
    def test_full_universe_contains_priority_manual_and_public_with_no_duplicates(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(full, 'ROOT', Path(temp)):
            root = Path(temp)
            def save(relative, value):
                path = root/relative;path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(encode(value), encoding='utf-8')
            save('.research/manual-downloads/全量采集资料.json', dict(units=[dict(name='重点大学',portal='https://a.edu.cn'),dict(name='手册大学',portal=None)]))
            save('.research/unit-dossiers-20261001/dossiers.json', [dict(unit='重点大学')])
            save('public.json', dict(units=[dict(name='重点大学'),dict(name='补充大学')]))
            save('.research/admissions-data/latest.json', dict(path=str(root/'public.json'),version_id='test'))
            save('.research/github-sources/latest.json', dict(repositories=[dict(repo='test/kaoyan-recommendation-platform',path=str(root/'repo'))]))
            save('repo/data/admission-units.json', dict(units=[dict(name='补充大学',sourceUrl='https://yz.chsi.com.cn/sch/1')]))
            plan=full.build_plan('2026-10-08')
            self.assertEqual(plan['units'], ['重点大学','补充大学','手册大学'])
            self.assertEqual(len(plan['jobs']), 24)
            self.assertEqual(len({j['id'] for j in plan['jobs']}), 24)
            self.assertEqual({j['platform'] for j in plan['jobs']},set(full.PLATFORMS))
            self.assertEqual(plan['corpus']['units'][1]['portal'],'https://yz.chsi.com.cn/sch/1')

    def test_blocked_and_unverified_are_not_reported_complete(self):
        plan=dict(as_of='2026-10-08', units=['A'], jobs=[dict(id='a')])
        self.assertFalse(full.summary(plan,{'a':dict(state='needs-human')})['fully_finished'])
        done=full.summary(plan,{'a':dict(state='committed')})
        self.assertTrue(done['fully_finished'])
        self.assertFalse(done['all_information_verified'])

    def test_checkpoint_resume_does_not_repeat_committed_jobs(self):
        import collect_social_sources as collection
        with tempfile.TemporaryDirectory() as temp, patch.object(full,'ROOT',Path(temp)), patch.object(collection,'ROOT',Path(temp)), patch.object(full.time,'sleep'):
            root=Path(temp);folder=root/'.research/full';folder.mkdir(parents=True)
            jobs=[]
            for unit in ['A','B']:
                for platform in full.PLATFORMS:
                    job=dict(unit=unit,platform=platform,keyword=unit,as_of='2026-10-08')
                    job['id']=digest(job);jobs.append(job)
            plan=dict(as_of='2026-10-08',units=['A','B'],jobs=jobs,limit=2)
            (folder/'plan.json').write_text(encode(plan),encoding='utf-8')
            calls=[]
            def collect(**kwargs):
                key=digest(dict(unit=kwargs['units_override'][0],platform=kwargs['platforms_override'][0]))
                calls.append(key);batch=root/key;batch.mkdir()
                (batch/'manifest.json').write_text(encode(dict(jobs=[])),encoding='utf-8')
                return dict(folder=str(batch),run_id=key,snapshots=1,database_state='committed')
            with patch.object(full,'run',side_effect=collect):
                full.execute(folder,max_jobs=4)
                full.execute(folder,max_jobs=4)
            self.assertEqual(len(calls),8)
            self.assertEqual(len(set(calls)),8)
            state=json.loads((folder/'state.json').read_text(encoding='utf-8'))
            self.assertEqual(len(state),8)
            self.assertFalse((root/'.research/social/full-run-active.json').exists())

    def test_paused_platform_leaves_jobs_unattempted(self):
        import collect_social_sources as collection
        with tempfile.TemporaryDirectory() as temp, patch.object(full,'ROOT',Path(temp)), \
                patch.object(collection,'ROOT',Path(temp)), patch.object(full.time,'sleep'):
            root=Path(temp);folder=root/'.research/full';folder.mkdir(parents=True)
            job=dict(unit='A',platform='xhs',keyword='A',as_of='2026-10-08');job['id']=digest(job)
            (folder/'plan.json').write_text(encode(dict(as_of='2026-10-08',units=['A'],jobs=[job],limit=2)),encoding='utf-8')
            collection.set_platform_health('xhs','needs-human','platform-verification-required')
            with patch.object(full,'run') as request:
                full.execute(folder)
                request.assert_not_called()
            report=json.loads((folder/'summary.json').read_text(encoding='utf-8'))
            self.assertEqual(report['dispatched'],0)
            self.assertFalse(report['fully_finished'])

    def test_interrupted_running_without_receipt_is_not_called_active_or_empty(self):
        import collect_social_sources as collection
        with tempfile.TemporaryDirectory() as temp, patch.object(full,'ROOT',Path(temp)), patch.object(collection,'ROOT',Path(temp)), patch.object(full.time,'sleep'):
            root=Path(temp);folder=root/'.research/full';folder.mkdir(parents=True)
            job=dict(unit='A',platform='xhs',keyword='A',as_of='2026-10-08');job['id']=digest(job)
            (folder/'plan.json').write_text(encode(dict(as_of='2026-10-08',units=['A'],jobs=[job],limit=2)),encoding='utf-8')
            (folder/'state.json').write_text(encode({job['id']:dict(job,state='running')}),encoding='utf-8')
            collection.set_platform_health('xhs','needs-human','platform-verification-required')
            with patch.object(full,'run') as request:full.execute(folder,max_jobs=0)
            request.assert_not_called()
            row=json.loads((folder/'state.json').read_text(encoding='utf-8'))[job['id']]
            self.assertEqual(row['state'],'interrupted-platform-paused');self.assertEqual(row['request_history'],'unknown')
            report=json.loads((folder/'summary.json').read_text(encoding='utf-8'))
            self.assertEqual(report['states'].get('running',0),0);self.assertFalse(report['fully_finished'])


if __name__=='__main__':unittest.main()
