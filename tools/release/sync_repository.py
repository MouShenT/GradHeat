"""Safe push and validated fast-forward updates for the user-authorized repo."""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

from stage_code import ROOT, audit, git
from check_source import command, immutable_migrations, validate

REMOTE = 'https://github.com/MouShenT/GradHeat'


class LockBusy(Exception):
    """Another process owns the protected operation."""


@contextmanager
def lock(folder):
    folder.mkdir(parents=True, exist_ok=True)
    with (folder/'run.lock').open('a+b') as stream:
        stream.seek(0); stream.write(b'0'); stream.flush(); stream.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            raise LockBusy('Operation already active') from error
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == 'nt':
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)


def record(root, action, state, **fields):
    folder = root/'.research/repo-sync'; folder.mkdir(parents=True, exist_ok=True)
    value = dict(action=action, state=state, checked_at=datetime.now(timezone.utc).isoformat(), **fields)
    pointer = folder/'latest.json'; temporary = folder/('latest-'+str(os.getpid())+'.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8'); temporary.replace(pointer)
    if action == 'push':
        (folder/'push.json').write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(value, ensure_ascii=False), flush=True)
    return value


def remote_valid(root=ROOT):
    observed = git('remote', 'get-url', 'origin', root=root).decode().strip().rstrip('/')
    if observed.endswith('.git'): observed = observed[:-4]
    if observed != REMOTE:
        raise ValueError('Repository origin differs from the authorized repository')


def clean(root=ROOT):
    # Ignored and untracked local data is preserved; tracked modifications block.
    from stage_code import allowed
    if git('status', '--porcelain', '--untracked-files=no', root=root).strip(): return False
    others = git('ls-files', '--others', '--exclude-standard', '-z', root=root).decode('utf-8').split('\0')
    return not any(allowed(path) for path in others if path)


def ancestor(before, after, root=ROOT):
    return subprocess.run(['git','merge-base','--is-ancestor',before,after],cwd=root,
                          stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode == 0


def update_state(root=ROOT):
    local = git('rev-parse', 'HEAD', root=root).decode().strip()
    remote = git('rev-parse', 'origin/main', root=root).decode().strip()
    if not clean(root): return dict(state='local-changes-preserved', local_sha=local, remote_sha=remote)
    if local == remote: return dict(state='up-to-date', local_sha=local, remote_sha=remote)
    if ancestor(local, remote, root): return dict(state='fast-forward-available', local_sha=local, remote_sha=remote)
    if ancestor(remote, local, root): return dict(state='local-commits-awaiting-push', local_sha=local, remote_sha=remote)
    return dict(state='diverged-preserved', local_sha=local, remote_sha=remote)


def fetch(root=ROOT):
    remote_valid(root)
    command(['git','fetch','--prune','origin'],root,root/'.research/repo-sync/private.log',120)


def push(root=ROOT):
    fetch(root)
    sha = git('rev-parse','HEAD',root=root).decode().strip()
    audit(sha,root=root)
    commits = git('rev-list',sha,'--not','--remotes=origin',root=root).decode().splitlines()
    for commit in commits:
        audit(commit,root=root)
    if not ancestor('origin/main',sha,root):
        return record(root,'push','remote-diverged-preserved',local_sha=sha)
    immutable_migrations('origin/main',sha,root)
    command(['git','push','origin','HEAD:refs/heads/main'],root,root/'.research/repo-sync/private.log',120)
    command(['git','fetch','origin','main'],root,root/'.research/repo-sync/private.log',120)
    if git('rev-parse','origin/main',root=root).decode().strip() != sha:
        raise RuntimeError('Remote commit readback differs')
    (root/'.research/repo-sync/deploy-request').write_text(sha,encoding='utf-8')
    return record(root,'push','pushed',local_sha=sha,remote_sha=sha)


def deploy(root, sha, checked):
    folder = root/'.research/application-builds'/sha
    folder.mkdir(parents=True,exist_ok=True)
    jar = folder/'gradheat-backend-0.1.0.jar'
    shutil.copyfile(checked['jar'],jar)
    if hashlib.sha256(jar.read_bytes()).hexdigest() != checked['jar_sha256']:
        raise ValueError('Build copy checksum mismatch')
    current = root/'.research/frontend-dev'
    if not (current/'config.json').is_file():
        return dict(state='code-updated-service-not-installed',source_sha=sha)
    pointer = current/'backend-build.json'; temporary = current/'backend-build.tmp'
    temporary.write_text(json.dumps(dict(jar=str(jar),source_sha=sha,jar_sha256=checked['jar_sha256'])),encoding='utf-8')
    temporary.replace(pointer)
    (current/'backend.restart').touch()
    deadline = time.monotonic()+250
    while time.monotonic()<deadline:
        try:
            runtime = json.loads((current/'runtime.json').read_text(encoding='utf-8'))
            if runtime.get('state') == 'ready' and runtime.get('backend_source_sha') == sha:
                return dict(state='deployed',source_sha=sha,jar=str(jar))
        except (OSError,ValueError):
            pass
        time.sleep(2)
    raise TimeoutError('Updated service readiness timeout')


def deployed_source(root=ROOT):
    try:
        runtime = json.loads((root/'.research/frontend-dev/runtime.json').read_text(encoding='utf-8'))
        if runtime.get('state') == 'ready':
            return runtime.get('backend_source_sha')
    except (OSError,ValueError):
        pass
    # A manager restart can precede API readiness. Reuse the already validated
    # installed artifact instead of rebuilding the same version during startup.
    try:
        build=json.loads((root/'.research/frontend-dev/backend-build.json').read_text(encoding='utf-8'))
        sha=build['source_sha'];jar=Path(build['jar']).resolve()
        if len(sha) not in (40,64) or any(c not in '0123456789abcdef' for c in sha):return None
        expected=(root/'.research/application-builds'/sha/'gradheat-backend-0.1.0.jar').resolve()
        if jar==expected and hashlib.sha256(jar.read_bytes()).hexdigest()==build['jar_sha256']:
            return sha
    except (OSError,ValueError,KeyError,TypeError):
        pass
    return None


def pull(root=ROOT, should_deploy=False):
    fetch(root)
    status = update_state(root)
    if status['state'] == 'local-commits-awaiting-push':
        outcome = push(root)
        if outcome['state'] != 'pushed':
            return outcome
        status = update_state(root)
    if status['state'] not in {'up-to-date','fast-forward-available'}:
        return record(root,'pull',**status)
    sha = status['remote_sha']
    deployed = deployed_source(root)
    if status['state'] == 'up-to-date' and (not should_deploy or deployed == sha):
        request = root/'.research/repo-sync/deploy-request'
        if request.is_file() and request.read_text(encoding='utf-8').strip() == sha:
            request.unlink()
        return record(root,'pull',**status)
    audit(sha,root=root)
    immutable_migrations(status['local_sha'],sha,root)
    with lock(root/'.research/daily-update'):
        pass  # Defer before building if a collector is currently active.
    checked = validate(sha,root=root)
    with lock(root/'.research/daily-update'):
        # A developer or collector may have changed state during the build.
        if not clean(root) or git('rev-parse','HEAD',root=root).decode().strip() != status['local_sha']:
            return record(root,'pull',state='local-changes-preserved',remote_sha=sha)
        lock_changed = git('diff','--name-only',status['local_sha'],sha,'frontend/package-lock.json',root=root).strip()
        if status['state'] == 'fast-forward-available':
            command(['git','merge','--ff-only',sha],root,root/'.research/repo-sync/private.log',60)
        if lock_changed:
            npm=shutil.which('npm.cmd' if os.name=='nt' else 'npm')
            command([npm,'ci','--ignore-scripts','--prefer-offline','--no-audit','--no-fund'],root/'frontend',root/'.research/repo-sync/private.log')
            (root/'.research/frontend-dev/frontend.restart').touch()
        outcome = deploy(root,sha,checked) if should_deploy else dict(state='code-updated',source_sha=sha)
    (root/'.research/repo-sync/deploy-request').unlink(missing_ok=True)
    return record(root,'pull',**outcome)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=('push','pull'))
    parser.add_argument('--deploy',action='store_true');parser.add_argument('--from-hook',action='store_true')
    args=parser.parse_args()
    try:
        with lock(ROOT/'.research/repo-sync'):
            result=push() if args.action=='push' else pull(should_deploy=args.deploy)
        if result['state'] in {'remote-diverged-preserved','diverged-preserved'}:
            raise SystemExit(1)
    except LockBusy:
        record(ROOT,args.action,'operation-active-deferred')
        raise SystemExit(0)
    except Exception as error:
        # Infrastructure stderr remains local; do not disclose credentials.
        record(ROOT,args.action,'needs-attention',error_type=type(error).__name__)
        raise SystemExit(0 if args.from_hook else 1)


if __name__=='__main__':main()
