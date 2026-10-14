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


def _execute(plan, folder, hours=8):
    if set(plan) != {'schema_version','batches'} or plan['schema_version'] != 1:
        raise ValueError('Explicit collection queue required')
    if not 1 <= len(plan['batches']) <= 2000 or not .01 <= hours <= 72:
        raise ValueError('Queue or time budget outside range')
    for batch in plan['batches']:
        validate(batch)
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


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--input',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True);parser.add_argument('--hours',type=float,default=8)
    args=parser.parse_args()
    print(canonical(execute(json.loads(args.input.read_text(encoding='utf-8-sig')),args.output,args.hours)),flush=True)
