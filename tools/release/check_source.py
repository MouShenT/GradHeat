"""Export and validate a Git source tree without local datasets or credentials."""
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import zipfile

from stage_code import ROOT, audit, git


def command(argv, cwd, log, timeout=600):
    with log.open('ab') as stream:
        result = subprocess.run(argv, cwd=cwd, stdin=subprocess.DEVNULL, stdout=stream,
                                stderr=subprocess.STDOUT, timeout=timeout,
                                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    if result.returncode:
        raise RuntimeError('Source check failed; inspect local log: ' + log.name)


def immutable_migrations(old, new, root=ROOT):
    paths = git('ls-tree', '-r', '--name-only', old, 'crawler/sql', root=root).decode().splitlines()
    for path in paths:
        if git('show', old+':'+path, root=root) != git('show', new+':'+path, root=root):
            raise ValueError('Previously committed migration changed: ' + path)


def validate(ref, root=ROOT, build=True):
    source_audit = audit(ref, root=root)
    parent = root/'.research/code-release-check'
    parent.mkdir(parents=True, exist_ok=True)
    folder = Path(tempfile.mkdtemp(prefix='source-', dir=parent)).resolve()
    with zipfile.ZipFile(io.BytesIO(git('archive', '--format=zip', ref, root=root))) as archive:
        for item in archive.infolist():
            target = (folder/item.filename).resolve()
            if not target.is_relative_to(folder):
                raise ValueError('Archive path outside source checkout')
            archive.extract(item, folder)
    checks = [dict(name='complete-source-audit', **source_audit)]
    log = parent/(folder.name+'.private.log')
    command([sys.executable, '-X', 'utf8', '-B', '-m', 'unittest', 'discover', '-s', 'python_service/tests'], folder, log, 180)
    checks.append(dict(name='python-core-api-collection', passed=True))
    command([sys.executable, '-X', 'utf8', '-B', '-m', 'unittest', 'discover', '-s', 'tools/release/tests'], folder, log, 180)
    checks.append(dict(name='repository-sync-protections', passed=True))
    jar = None
    if build:
        npm = shutil.which('npm.cmd' if os.name == 'nt' else 'npm')
        maven = shutil.which('mvn.cmd' if os.name == 'nt' else 'mvn')
        if not npm or not maven:
            raise RuntimeError('Node/npm and Maven are required')
        command([npm, 'ci', '--ignore-scripts', '--prefer-offline', '--no-audit', '--no-fund'], folder/'frontend', log)
        command([npm, 'test'], folder/'frontend', log)
        command([npm, 'run', 'build'], folder/'frontend', log)
        checks.append(dict(name='vue-tests-types-production-build', passed=True))
        command([maven, '-B', '-q', '-f', str(folder/'backend/pom.xml'), 'verify'], folder, log)
        jar = folder/'backend/target/gradheat-backend-0.1.0.jar'
        if not jar.is_file():
            raise RuntimeError('Verified Java artifact missing')
        checks.append(dict(name='java-business-message-http-build', passed=True))
    report = dict(passed=True, source_ref=ref, checked_at=datetime.now(timezone.utc).isoformat(),
                  checkout=str(folder), checks=checks, log=str(log), jar=str(jar) if jar else None,
                  jar_sha256=hashlib.sha256(jar.read_bytes()).hexdigest() if jar else None)
    receipt = parent/(folder.name+'-verification.json')
    receipt.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return report
