"""Test the exact staged source closure, without copying local research data."""
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[2]


def main():
    parent=ROOT/'.research/code-release-check';parent.mkdir(parents=True,exist_ok=True)
    folder=Path(tempfile.mkdtemp(prefix=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ-'),dir=parent))
    checks=[]
    paths=subprocess.check_output(['git','ls-files','crawler/sql/*.sql'],cwd=ROOT).decode().splitlines()
    for path in paths:
        body=subprocess.check_output(['git','show',':'+path],cwd=ROOT)
        if body!=(ROOT/path).read_bytes():raise ValueError('Staged migration bytes differ: '+path)
        checks.append({'name':'migration-byte-preservation','path':path,'sha256':hashlib.sha256(body).hexdigest(),'passed':True})
    subprocess.run(['git','checkout-index','--all','--prefix='+folder.as_posix()+'/'],cwd=ROOT,check=True)
    for suite in ('python_service/tests','workbench/tests'):
        log=folder.parent/(folder.name+'-'+suite.replace('/','-')+'.private.log')
        with log.open('wb') as stream:
            result=subprocess.run([sys.executable,'-X','utf8','-B','-m','unittest','discover','-s',suite],cwd=folder,
                stdout=stream,stderr=subprocess.STDOUT,timeout=180)
        checks.append({'name':'fresh-staged-test-suite','suite':suite,'passed':result.returncode==0,'log':str(log)})
        if result.returncode:print(log.read_text(encoding='utf-8')[-8000:])
    report={'checked_at':datetime.now(timezone.utc).isoformat(),'checkout':str(folder),'checks':checks}
    target=folder.parent/(folder.name+'-verification.json');target.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    passed=all(c['passed'] for c in checks)
    print(json.dumps({'passed':passed,'checks':len(checks),'report':str(target)}))
    if not passed:raise SystemExit(1)


if __name__=='__main__':main()
