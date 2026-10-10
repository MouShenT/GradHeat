"""Live API and MySQL round trip; synthetic inputs are rolled back, never published."""
import hashlib
import json
import sys
import uuid
from contextlib import contextmanager
from pathlib import Path
from urllib.request import Request, urlopen

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'workbench'));sys.path.insert(0,str(ROOT/'crawler'))
from gradheat.vm_db import connect_vm
from gradheat_workbench.comparison_archive import MySQLComparisonArchive, migrate
from gradheat_workbench.admissions_decision import publication_version


def main():
    runtime=ROOT/'.research/decision-workbench/runtime.json'
    base=json.loads(runtime.read_text(encoding='utf-8-sig'))['url'].rstrip('/') if runtime.exists() else 'http://127.0.0.1:18727'
    with urlopen(base+'/api/admissions',timeout=30) as response:
        payload=json.load(response);version=response.headers['X-Data-Version']
    assert publication_version(payload)==version
    selected=[p for p in payload['programmes'] if p['unit']=='中国人民大学' and p['eligible_11408']][:2]
    assert len(selected)==2
    request=dict(title='流程验收（非个人择校结论）'+uuid.uuid4().hex[:8],data_version=version,candidates=[dict(programme_id=p['id']) for p in selected])
    with urlopen(Request(base+'/api/admissions/compare',data=json.dumps(request).encode(),headers={'Content-Type':'application/json'},method='POST'),timeout=30) as response:
        result=json.load(response)
    assert result['data_version']==version
    assert all(x['low']==0 and x['high']==10 for x in result['baseline']['intervals'].values())
    assert all('https://' not in json.dumps(x) and 'source_url' not in json.dumps(x) for x in result['cards'])
    for card in result['cards']:
        if card['programme']['major_code']=='081200':assert all('计算机科学与技术' in h['major_name'] for h in card['history'])
        if card['programme']['major_code']=='0812Z3':assert all('人工智能' in h['major_name'] for h in card['history'])
    folder=ROOT/'.research/workbench-acceptance-20261005';folder.mkdir(parents=True,exist_ok=True)
    with connect_vm(folder) as con:
        migrate(con,ROOT)
        with con.cursor() as cur:
            cur.execute('SELECT COUNT(*) FROM personal_comparison');before=cur.fetchone()[0]
        con.commit()
        class RollbackOnly:
            def cursor(self):return con.cursor()
            def commit(self):pass
            def rollback(self):con.rollback()
        @contextmanager
        def transaction():yield RollbackOnly()
        archive=MySQLComparisonArchive(ROOT,connect=transaction)
        try:
            first=archive.save(result);cid=first['comparison_id']
            assert not first['reused']
            assert archive.save(result)['reused']
            stored=archive.get(cid)
            assert stored['result']==result
            assert 'https://' not in stored['report_md']
            assert any(x['comparison_id']==cid for x in archive.list())
            with con.cursor() as cur:cur.execute('UPDATE personal_comparison SET report_md=%s WHERE comparison_id=%s',('验收篡改测试',cid))
            try:archive.get(cid)
            except ValueError:pass
            else:raise AssertionError('Corrupt comparison was not rejected')
        finally:con.rollback()
        with con.cursor() as cur:
            cur.execute('SELECT COUNT(*) FROM personal_comparison');after=cur.fetchone()[0]
            cur.execute('SELECT COUNT(*) FROM personal_comparison WHERE comparison_id=%s',(cid,));remaining=cur.fetchone()[0]
        con.commit()
        assert before==after and remaining==0
    report=dict(live_compare=True,version_header_matches=True,programme_history_aligned=True,
        mysql_save_readback=True,idempotent_save=True,immutable_record_verified=True,corruption_rejected=True,
        test_data_rolled_back=True,user_records_before=before,user_records_after=after,
        data_version=version,implementation_sha256=result['implementation_sha256'],verified_on='2026-10-05')
    (folder/'comparison-flow-check.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False))


if __name__=='__main__':main()
