"""Explicit code-only staging. Collected records and credentials cannot be added.

Use --stage only after review; --audit-index checks the exact staged additions.
Private-env/json inputs are optional local value checks and are never printed.
"""
import argparse
import json
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[2]
DIRECTORIES=('frontend','backend','python_service','config','workbench/gradheat_workbench',
    'workbench/static','workbench/tests','crawler/gradheat','crawler/sql',
    'tools/application','tools/integration','tools/release','contracts/application-v1')
FILES=('.gitignore','.gitattributes','.dockerignore','README.md','infra/docker/.env.example','contracts/runtime-connections.example.json',
    'contracts/social-collection.json','workbench/run.py','workbench/requirements.txt',
    'tools/build-application.ps1','tools/start-application.ps1','tools/run-collection.ps1',
    'docs/IMPLEMENTATION-PLAN-20261009.md','docs/JAVA-PYTHON-ARCHITECTURE-20261009.md',
    'docs/FRONTEND-MIGRATION-20261009.md','docs/JAVA-BACKEND-20261009.md',
    'docs/PYTHON-SERVICE-20261009.md','docs/INTEGRATION-20261009.md','docs/APPLICATION-RUNBOOK.md',
    'docs/AUTONOMOUS-COLLECTION-PLAN-20261010.md','docs/AUTONOMOUS-COLLECTION-RUNBOOK.md')
COLLECTORS=('audit_dossier_availability','build_comparison_draft','build_download_index',
    'build_full_collection_coverage','build_unit_dossiers','check_latest_notices',
    'collect_gap_round2','collect_priority_sources','collect_social_sources','compare_github_sources',
    'extract_admission_statistics','extract_dossier_evidence','fetch_github_sources',
    'mediacrawler_worker','open_social_login','recover_gap_tls','refine_download_resources',
    'refresh_dossier_sources','resume_social_backlog','review_social_access',
    'run_full_social_collection','social_evidence','supplement_missing_sources',
    'validate_unit_dossiers','verify_comparison_flow','verify_corroboration','verify_social_storage')
FORBIDDEN_PARTS={'.research','.firecrawl','node_modules','target','dist','__pycache__','.venv','venv','data'}
FORBIDDEN_SUFFIXES={'.jsonl','.csv','.xlsx','.xls','.pdf','.png','.jpg','.zip','.sqlite','.sqlite3','.db','.dump','.log','.har','.pem','.key','.pyc'}
REMOVED_PRIVATE={'infra/docker/.env','crawler/data/school_portal.20260922T170805Z.jsonl','crawler/data/yz_school_list.20260918T111110Z.jsonl'}


def safe_path(path):
    value=Path(path)
    if any(part in FORBIDDEN_PARTS for part in value.parts) or value.suffix.lower() in FORBIDDEN_SUFFIXES:
        return False
    if value.name.startswith('.env') and value.name!='.env.example':
        return False
    if value.as_posix().startswith('docs/units/') or value.as_posix()=='contracts/runtime-connections.json':
        return False
    return True


def git(*args):
    return subprocess.check_output(['git',*args],cwd=ROOT)


def selected_paths():
    selected=set()
    for folder in DIRECTORIES:
        base=ROOT/folder
        if base.is_dir():
            selected.update(p.relative_to(ROOT).as_posix() for p in base.rglob('*') if p.is_file() and safe_path(p.relative_to(ROOT)))
    selected.update(p for p in FILES if (ROOT/p).is_file())
    selected.update('tools/research/'+name+'.py' for name in COLLECTORS if (ROOT/'tools/research'/f'{name}.py').is_file())
    selected.update(p.relative_to(ROOT).as_posix() for p in (ROOT/'crawler').glob('run_*.py'))
    return sorted(selected)


def strings(value):
    if isinstance(value,dict):
        for item in value.values(): yield from strings(item)
    elif isinstance(value,list):
        for item in value: yield from strings(item)
    elif isinstance(value,str) and len(value)>=12:
        yield value.encode('utf-8')


def audit(allowed, needles):
    added=git('diff','--cached','--name-only','--diff-filter=ACMRT','-z').decode('utf-8').split('\0')
    removed=git('diff','--cached','--name-only','--diff-filter=D','-z').decode('utf-8').split('\0')
    failures=[]
    for path in filter(None,added):
        if path not in allowed or not safe_path(path):
            failures.append({'path':path,'reason':'outside-code-allowlist'})
        body=git('show',':'+path)
        if any(secret in body for secret in needles):
            failures.append({'path':path,'reason':'contains-private-value'})
        if len(body)>3_000_000:
            failures.append({'path':path,'reason':'unexpected-large-code-file'})
    for path in filter(None,removed):
        if path not in allowed and path not in REMOVED_PRIVATE:
            failures.append({'path':path,'reason':'unreviewed-deletion'})
    if failures:
        print(json.dumps({'passed':False,'failures':failures},ensure_ascii=False))
        raise SystemExit(1)
    print(json.dumps({'passed':True,'staged_code_files':len(list(filter(None,added))),
        'private_files_untracked':len([p for p in removed if p in REMOVED_PRIVATE])},ensure_ascii=False))


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--stage',action='store_true')
    parser.add_argument('--audit-index',action='store_true')
    parser.add_argument('--private-env',action='append',default=[])
    parser.add_argument('--private-json',action='append',default=[])
    args=parser.parse_args()
    selected=selected_paths();needles=[]
    for name in args.private_env:
        path=Path(name)
        for line in path.read_text(encoding='utf-8').splitlines():
            if not line.lstrip().startswith('#') and '=' in line:
                key,value=line.split('=',1)
                if any(term in key.upper() for term in ('PASSWORD','TOKEN','SECRET','API_KEY')) and len(value.strip())>=12:
                    needles.append(value.strip().encode())
    for name in args.private_json:
        needles.extend(strings(json.loads(Path(name).read_text(encoding='utf-8'))))
    if args.stage:
        branch=git('branch','--show-current').decode().strip()
        if not branch.startswith('codex/'):
            raise SystemExit('Use an isolated codex/ branch before staging.')
        for offset in range(0,len(selected),60):
            subprocess.run(['git','add','--',*selected[offset:offset+60]],cwd=ROOT,check=True)
    if args.stage or args.audit_index:
        audit(set(selected),needles)
    else:
        print(json.dumps({'code_file_count':len(selected),'files':selected},ensure_ascii=False,indent=2))


if __name__=='__main__': main()
