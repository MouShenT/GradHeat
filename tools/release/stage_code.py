"""Select and audit the maintained source closure, never local data."""
import argparse
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOTS = ('frontend/', 'backend/', 'python_service/', 'crawler/gradheat/', 'crawler/sql/',
                'crawler/refs/', 'tools/application/', 'tools/integration/', 'tools/release/', 'infra/')
FILES = {
    'AGENTS.md', 'README.md', '.gitignore', '.gitattributes', '.dockerignore', '.mcp.json.example',
    '.githooks/post-commit', 'config/collection-input.example.json', 'config/collection-keywords.json',
    'config/parallel-collection.example.json',
    'config/collection-policy.json', 'contracts/README.md', 'contracts/social-collection.json',
    'contracts/runtime-connections.example.json', 'contracts/application-v1/README.md',
    'crawler/README.md', 'crawler/.env.example', 'crawler/run_daily_update.py',
    'crawler/run_archive_materials.py', 'crawler/run_import_research.py', 'crawler/run_migrate_application.py',
    'crawler/run_publish_admissions.py', 'crawler/run_research_status.py', 'crawler/run_school_list.py',
    'crawler/run_find_portal.py', 'crawler/test_portal.py', 'crawler/scripts/list_schools.py', 'crawler/scripts/verify_refs.py',
    'tools/build-application.ps1', 'tools/start-application.ps1', 'tools/start-frontend.ps1',
    'tools/run-collection.ps1', 'tools/打开前端.cmd', 'tools/打开采集登录.cmd',
    'docs/ARCHITECTURE.md', 'docs/STATUS.md', 'docs/TASKS.md', 'docs/ALGORITHMS.md',
    'docs/APPLICATION-RUNBOOK.md', 'docs/AUTONOMOUS-COLLECTION-RUNBOOK.md',
    'docs/FRONTEND-DEV-SERVICE.md', 'docs/RESEARCH-EVIDENCE-POLICY.md',
    'docs/SOCIAL-COLLECTOR-SELECTION.md', 'docs/REPOSITORY-SYNC.md',
}
COLLECTORS = {
    'audit_dossier_availability', 'build_comparison_draft', 'build_download_index', 'build_full_collection_coverage',
    'build_unit_dossiers', 'check_latest_notices', 'collect_gap_round2', 'collect_priority_sources',
    'collect_social_sources', 'compare_github_sources', 'extract_admission_statistics', 'extract_dossier_evidence',
    'fetch_github_sources', 'mediacrawler_worker', 'open_social_login', 'recover_gap_tls',
    'refine_download_resources', 'refresh_dossier_sources', 'resume_social_backlog', 'review_social_access',
    'run_full_social_collection', 'social_evidence', 'supplement_missing_sources', 'validate_unit_dossiers',
    'build_intelligence_queries', 'collect_search_indices', 'queue_intelligence_collection', 'refresh_school_intelligence',
    'expand_school_basics', 'evaluate_index_models', 'collect_community_sources', 'collect_parallel_sources', 'zhihu_browser_search',
}
FILES.update('tools/research/' + name + '.py' for name in COLLECTORS)
FILES.update('tools/research/' + name for name in ('firecrawl.ps1', 'searxng.ps1', 'agent-browser.ps1', 'requirements-search-index.txt'))
FORBIDDEN_PARTS = {'.research', '.firecrawl', 'node_modules', 'target', 'dist', '__pycache__', '.venv', 'venv', 'data', 'units'}
SOURCE_SUFFIXES = {'.py', '.java', '.ts', '.vue', '.css', '.js', '.json', '.xml', '.yml', '.yaml', '.sql', '.md', '.txt', '.ps1', '.cmd', '.html'}


def safe_path(path):
    path = Path(path)
    if path.is_absolute() or '..' in path.parts or any(p in FORBIDDEN_PARTS for p in path.parts):
        return False
    if path.name.startswith('.env') and path.name != '.env.example':
        return False
    return True


def allowed(path):
    if not safe_path(path):
        return False
    if path in FILES:
        return True
    if not path.startswith(SOURCE_ROOTS):
        return False
    item = Path(path)
    if item.suffix not in SOURCE_SUFFIXES and item.name not in {'Dockerfile', '.env.example', '.gitignore'}:
        return False
    if item.suffix == '.json' and path not in {'frontend/package.json', 'frontend/package-lock.json', 'frontend/tsconfig.json'}:
        return '/tests/' in path
    return True


def git(*args, root=ROOT):
    return subprocess.check_output(['git', *args], cwd=root)


def private_values(root=ROOT):
    values = set()
    for path in (root/'infra/docker/.env', root/'crawler/.env', root/'backend/.env', root/'python_service/.env'):
        if not path.is_file():
            continue
        for line in path.read_text(encoding='utf-8-sig').splitlines():
            if line.lstrip().startswith('#') or '=' not in line:
                continue
            key, value = line.split('=', 1)
            if any(term in key.upper() for term in ('PASSWORD', 'TOKEN', 'SECRET', 'API_KEY')) and len(value.strip()) >= 8:
                values.add(value.strip().encode())
    cookie = root/'.research/school-intelligence/private/baidu-cookies.json'
    if cookie.is_file():
        def visit(value):
            if isinstance(value, dict):
                if value.get('name', '').upper() in {'BDUSS', 'STOKEN', 'BDUSS_BFESS'} and len(value.get('value', '')) >= 12:
                    values.add(value['value'].encode())
                for item in value.values():
                    visit(item)
            elif isinstance(value, list):
                for item in value:
                    visit(item)
        visit(json.loads(cookie.read_text(encoding='utf-8')))
    mcp_config = root/'.mcp.json'
    if mcp_config.is_file():
        def secrets(value):
            if isinstance(value, dict):
                for key, item in value.items():
                    if isinstance(item, str) and any(term in key.upper() for term in ('PASSWORD','TOKEN','SECRET','KEY','AUTHORIZATION')) and len(item) >= 8:
                        values.add(item.encode())
                        if item.startswith('Bearer '): values.add(item[7:].encode())
                    secrets(item)
            elif isinstance(value, list):
                for item in value: secrets(item)
        secrets(json.loads(mcp_config.read_text(encoding='utf-8')))
    return values


def audit(ref='HEAD', root=ROOT, needles=None):
    needles = private_values(root) if needles is None else needles
    entries = git('ls-files', '-z', root=root) if ref == ':' else git('ls-tree', '-r', '--name-only', '-z', ref, root=root)
    paths = list(filter(None, entries.decode('utf-8').split('\0')))
    failures = []
    for path in paths:
        if not allowed(path):
            failures.append({'path': path, 'reason': 'outside-maintained-source'})
            continue
        body = git('show', ':' + path if ref == ':' else ref + ':' + path, root=root)
        if len(body) > 3_000_000 or b'\0' in body:
            failures.append({'path': path, 'reason': 'binary-or-unexpected-size'})
        if any(value in body for value in needles):
            failures.append({'path': path, 'reason': 'private-value'})
    if failures:
        raise ValueError(json.dumps({'source_audit_failed': failures}, ensure_ascii=False))
    return {'passed': True, 'source_files': len(paths)}


def stage():
    tracked = set(filter(None, git('ls-files', '-z').decode('utf-8').split('\0')))
    candidates = set(filter(None, git('ls-files', '--others', '--exclude-standard', '-z').decode('utf-8').split('\0'))) | tracked
    selected = sorted(path for path in candidates if allowed(path) and (ROOT/path).is_file())
    removed = sorted(path for path in tracked if not (ROOT/path).exists())
    for offset in range(0, len(selected), 50):
        result = subprocess.run(['git', 'add', '--', *selected[offset:offset+50]], cwd=ROOT, capture_output=True)
        result.check_returncode()
    if removed:
        result = subprocess.run(['git', 'add', '-u', '--', *removed], cwd=ROOT, capture_output=True)
        result.check_returncode()
    return audit(':')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--stage', action='store_true')
    parser.add_argument('--audit-index', action='store_true')
    parser.add_argument('--ref', default='HEAD')
    args = parser.parse_args()
    result = stage() if args.stage else audit(':' if args.audit_index else args.ref)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
