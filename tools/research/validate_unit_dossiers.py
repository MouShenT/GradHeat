"""Check evidence references, pool totals and the delivered dossier inventory."""
import ast
import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import unquote
import build_unit_dossiers as d

def run():
    priority=d.priority.load()
    summary=d.read(d.WORK/'summary.json',[])
    claims=d.load_claims()
    stats=d.read(d.WORK/'admission-statistics-candidates.json',[])
    missing=d.read(d.WORK/'missing-fields.json',[])
    availability=d.read(d.WORK/'material-availability.json',[])
    checked_dates={x['unit']:x['checked_at'] for x in availability}
    assert len(summary)==68 and Counter(x['group'] for x in summary)=={'985':39,'计算机强校':19,'研究所':10}
    assert {x['name'] for x in summary}=={x['name'] for x in priority}
    priority_paths={Path(x['path']).resolve() for x in summary}
    delivered={p.resolve() for group in ('985','计算机强校','研究所') for p in (d.OUT/group).glob('*.md')}
    assert len(priority_paths)==68 and delivered==priority_paths
    assert all(p.is_file() for p in priority_paths)
    # Other candidate templates have been added since the original 70-file
    # delivery. They do not change the 68 priority dossiers' review scope.
    assert (d.OUT/'README.md').is_file() and (d.OUT/'缺失信息汇总.md').is_file()
    assert all(x['search_batches']>0 for x in summary)
    gaprows=[x for x in (d.OUT/'缺失信息汇总.md').read_text(encoding='utf-8').splitlines() if x.startswith('| [')]
    assert len(gaprows)==len({x['unit'] for x in missing})
    assert len(availability)==68
    assert {x['unit'] for x in availability}=={x['name'] for x in priority}
    for item in availability:
        assert item['unit_coverage_complete'] is False
        for year, fields in item['availability'].items():
            for field, evidence in fields.items():
                assert evidence and not any(m['unit']==item['unit'] and m['year']==int(year) and m['field']==field for m in missing)
                for source in evidence:
                    assert source['url'].startswith(('http://','https://'))
                    if source['artifact']:assert Path(source['artifact']).is_file()
    assert not any(x['year']==2027 and x['field']=='专业目录' and x['unit'] in ('复旦大学','华中师范大学','西安微电子技术研究所','中国海洋大学') for x in missing)
    assert not any(x['year']==2025 and x['unit']=='中国农业大学' and x['field']=='录取人数' for x in missing)
    # A soldiers-only directory and an expired roster announcement do not
    # satisfy the corresponding ordinary catalogue/result availability.
    assert any(x['unit']=='吉林大学' and x['year']==2027 and x['field']=='专业目录' for x in missing)
    assert any(x['unit']=='华东师范大学' and x['year']==2026 and x['field']=='录取人数' for x in missing)
    assert len(d.read(d.WORK/'review-queue.json',[]))==612
    links=0
    for unit in summary:
        path=Path(unit['path']);text=path.read_text(encoding='utf-8')
        assert all(f'## {year}' in text for year in (2027,2026,2025))
        assert text.count('缺失信息汇总')>=2
        assert '更新日期：'+checked_dates[unit['name']]+'。' in text
        for target in re.findall(r'\]\((<[^>]+>|[^)]+)\)',text):
            target=target.strip('<>')
            if re.match(r'https?://',target):continue
            target=unquote(target.split('#')[0])
            if not target:continue
            file=Path(target)
            if not file.is_absolute():file=path.parent/file
            assert file.is_file(),(path,target)
            links+=1
        if unit['name']=='西安微电子技术研究所':
            assert not any(n in text for n in ['嘉兴大学','江苏海洋大学','西北民族大学','浙江理工大学'])
            assert '其中0812计算机科学与技术12人' in text
    hashes={}
    assert len({x['claim_id'] for x in claims})==len(claims)
    for claim in claims:
        assert not claim['unit_coverage_complete']  # Partial reviews cannot close whole-unit gaps.
        assert claim['year'] in (2027,2026,2025)
        for s in claim['sources']:
            file=Path(s['artifact']);assert file.is_file()
            if str(file) not in hashes:hashes[str(file)]=hashlib.sha256(file.read_bytes()).hexdigest()
            assert hashes[str(file)]==s['sha256'],s['url']
    documents=defaultdict(list)
    for g in stats:
        assert isinstance(g['n'],int) and g['n']>0
        assert 100<=g['minimum']<=g['median']<=g['maximum']<=500
        assert g['minimum']<=g['mean']<=g['maximum']
        documents[(g['unit'],g['year'],g['source_url'])].append(g)
        path=Path(g['source_artifact']);assert path.is_file()
        if str(path) not in hashes:hashes[str(path)]=hashlib.sha256(path.read_bytes()).hexdigest()
        assert hashes[str(path)]==g['source_sha256']
    for groups in documents.values():
        assert sum(x['n'] for x in groups)==groups[0]['source_document_candidate_count']
    # Independent totals read visually / explicitly declared by original notices.
    for name,year,key,n in [
        ('清华大学',2026,'0D83FE4234DD470256A1FC6788F',15),
        ('清华大学',2025,'BC2A4C27C9C5DADDC2E37278F24',16),
        ('中国科学院计算机网络信息中心',2025,'t20250402_7586887',40),
        ('中国科学院计算机网络信息中心',2026,'t20260331_8179552',39),
        ('中国科学院计算机网络信息中心',2026,'t20260403_8181673',6),
        ('中国科学院信息工程研究所',2026,'t20260403_8181360',145),
        ('中国科学院信息工程研究所',2025,'t20250407_8093324',3),
    ]:
        assert sum(x['n'] for x in stats if x['unit']==name and x['year']==year and key in x['source_url'])==n,(name,year,n)
    cs=[x for x in stats if x['unit']=='清华大学' and x['year']==2026 and '0D83FE4234DD470256A1FC6788F' in x['source_url']]
    assert sorted(x['n'] for x in cs)==[2,13]
    # A four-digit subject code must stop header detection too.
    import extract_dossier_evidence as e
    import audit_dossier_availability as a
    assert not a.actual_count('预期26')
    assert not a.actual_count('331【309-380】')
    assert a.actual_count('24+11联培')
    assert e.starts_data(['生命科学与技术学院','生物学（0710）','315','50','90'])
    assert e.starts_data(['通信与信息系统（学硕）','50','45','80','90','310'])
    assert not e.starts_data(['专业代码','专业名称','单科（满分=100分）','总分'])
    assert not e.starts_data(['专业代码','专业名称','100','150'])
    assert not any(re.search(r'／\d{2,3}(?:／|$)',h) for r in d.read(d.WORK/'official-table-facts.json',[]) for h in r['headers']), 'Numerical data leaked into a table header'
    for path in Path(__file__).parent.glob('*dossier*.py'):ast.parse(path.read_text(encoding='utf-8'))
    ast.parse((Path(__file__).parent/'audit_dossier_availability.py').read_text(encoding='utf-8'))
    report=dict(units=len(summary),markdown_files=70,markdown_scope='priority dossiers plus index and single gap ledger',total_markdown_files=len(list(d.OUT.rglob('*.md'))),other_candidate_templates=len(list((d.OUT/'其他招生单位').glob('*.md'))),search_covered_units=68,reviewed_claims=len(claims),reviewed_units=len({x['unit'] for x in claims}),admission_candidate_groups=len(stats),admission_candidate_units=len({x['unit'] for x in stats}),missing_information_fields=len(missing),units_with_missing_information=len(gaprows),availability_audited_units=len(availability),hashes_checked=len(hashes),local_links_checked=links,status='passed')
    d.dump(d.WORK/'validation.json',report)
    print(json.dumps(report,ensure_ascii=False))

if __name__=='__main__':run()
