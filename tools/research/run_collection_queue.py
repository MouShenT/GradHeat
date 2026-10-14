"""Run frozen, bounded parallel batches in order using the existing collector."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from collect_parallel_sources import ROOT, validate
from gradheat_core.intelligence import canonical, digest
sys.path.insert(0,str(ROOT/'tools/application'))
from launcher import exclusive_lock
from runtime_json import write_runtime
from gradheat_python.collection_status import inspect


def validate_plan(plan,hours):
    if set(plan) != {'schema_version','batches'} or plan['schema_version'] != 1:
        raise ValueError('Explicit collection queue required')
    if not 1 <= len(plan['batches']) <= 2000 or not .01 <= hours <= 72:
        raise ValueError('Queue or time budget outside range')
    for batch in plan['batches']:
        validate(batch)


def _execute(plan, folder, hours=8):
    validate_plan(plan,hours)
    folder=Path(folder).resolve()
    if not folder.is_relative_to((ROOT/'.research').resolve()):
        raise ValueError('Private queue output required')
    folder.mkdir(parents=True,exist_ok=True)
    frozen=folder/'queue.json'
    body=canonical(plan)
    if frozen.exists() and frozen.read_text(encoding='utf-8') != body:
        raise ValueError('Frozen queue differs; preserve its existing run')
    frozen.write_text(body,encoding='utf-8')
    path=folder/'runtime.json'
    record=json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    # An interrupted child may have sent a request without retaining a receipt.
    # Do not turn a lost checkpoint into authorization to resend that batch.
    if record.get('current_batch') is not None:
        record.update(state='needs-review',reason='interrupted-batch-checkpoint')
        write_runtime(path,record)
        return record
    record=dict(record,pid=os.getpid(),queue_sha=digest(plan),total_batches=len(plan['batches']),state='running')
    started=time.monotonic()
    for index,batch in enumerate(plan['batches']):
        output=folder/f'batch-{index:04d}-{digest(batch)[:12]}'
        receipt=output/'report.json'
        if receipt.exists():
            if json.loads((output/'input.json').read_text(encoding='utf-8')) != batch:
                raise ValueError('Completed batch identity mismatch; do not refetch')
            json.loads(receipt.read_text(encoding='utf-8'))
            continue
        if time.monotonic()-started >= hours*3600:
            record.update(state='budget-ended',next_batch=index,current_batch=None)
            break
        source=folder/f'input-{index:04d}.json'
        source.write_text(canonical(batch),encoding='utf-8')
        record.update(current_batch=index,state='collecting',updated_at=datetime.now(timezone.utc).isoformat())
        write_runtime(path,record)
        with (folder/'collector.private.log').open('ab') as log:
            result=subprocess.run([sys.executable,'-X','utf8',str(ROOT/'tools/research/collect_parallel_sources.py'),
                '--input',str(source),'--output',str(output),'--social-workers','4','--wait-for-lock'],cwd=ROOT,stdout=log,stderr=log)
        if result.returncode or not receipt.exists():
            record.update(state='needs-review',reason='batch-retained-for-review',exit_code=result.returncode)
            break
        record.update(current_batch=None,processed_batches=index+1,updated_at=datetime.now(timezone.utc).isoformat())
        write_runtime(path,record)
    else:
        record.update(state='queue-processed',current_batch=None,processed_batches=len(plan['batches']))
    write_runtime(path,record)
    return record


def execute(plan, folder, hours=8):
    folder=Path(folder).resolve()
    if not folder.is_relative_to((ROOT/'.research').resolve()):
        raise ValueError('Private queue output required')
    with exclusive_lock(folder):
        return _execute(plan,folder,hours)


def execute_after(plan, folder, previous, hours=8):
    """Wait without collecting; uncertain upstream work is never restarted."""
    folder, previous=Path(folder).resolve(),Path(previous).resolve()
    if folder==previous or not all(p.is_relative_to((ROOT/'.research').resolve()) for p in (folder,previous)):
        raise ValueError('Separate private queue folders required')
    validate_plan(plan,hours)
    with exclusive_lock(folder):
        existing=json.loads((folder/'runtime.json').read_text(encoding='utf-8')) if (folder/'runtime.json').exists() else {}
        if existing.get('current_batch') is not None:
            return _execute(plan,folder,hours)
        frozen=folder/'queue.json';body=canonical(plan)
        if frozen.exists() and frozen.read_text(encoding='utf-8')!=body:
            raise ValueError('Frozen followup queue differs; preserve its existing run')
        frozen.write_text(body,encoding='utf-8')
        started=time.monotonic()
        while True:
            upstream=inspect(ROOT,previous)
            record=dict(existing,pid=os.getpid(),state='waiting-for-existing-queue',current_batch=None,
                queue_sha=digest(plan),total_batches=len(plan['batches']),processed_batches=existing.get('processed_batches',0),
                updated_at=datetime.now(timezone.utc).isoformat())
            if upstream.get('receipt_readable'):
                state=upstream['state']
                if state=='needs-review' or upstream.get('fault')=='owner-exited':
                    record.update(state='needs-review',reason='upstream-needs-review')
                    write_runtime(folder/'runtime.json',record)
                    return record
                if upstream.get('owner_alive') is False and state in ('budget-ended','queue-processed'):
                    return _execute(plan,folder,hours)
            if time.monotonic()-started>=24*3600:
                record.update(state='needs-review',reason='upstream-wait-budget-ended')
                write_runtime(folder/'runtime.json',record)
                return record
            write_runtime(folder/'runtime.json',record)
            time.sleep(15)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--input',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True);parser.add_argument('--hours',type=float,default=8)
    parser.add_argument('--after-queue',type=Path)
    args=parser.parse_args()
    plan=json.loads(args.input.read_text(encoding='utf-8-sig'))
    result=execute_after(plan,args.output,args.after_queue,args.hours) if args.after_queue else execute(plan,args.output,args.hours)
    print(canonical(result),flush=True)
