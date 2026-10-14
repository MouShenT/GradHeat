"""Watch one existing collector; never start, stop, or retry its requests."""
import argparse
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT/'python_service'), str(ROOT/'tools/application')]
from gradheat_python.collection_status import inspect, ProgressTracker, TERMINAL
from launcher import exclusive_lock
from runtime_json import write_runtime


def watch(queue, output, interval=15):
    if not 5 <= interval <= 300:
        raise ValueError('Monitor interval must be 5–300 seconds')
    output = Path(output).resolve()
    if not output.is_relative_to((ROOT/'.research').resolve()):
        raise ValueError('Private monitor output required')
    with exclusive_lock(output):
        tracker = ProgressTracker(); previous = None
        write_runtime(output/'runtime.json', dict(pid=os.getpid(), state='watching'))
        try:
            while True:
                report = tracker.observe(inspect(ROOT, queue), time.monotonic())
                write_runtime(output/'latest.json', report)
                # Retain useful events, never the raw queries, cookies or paths.
                key = json.dumps({k:report.get(k) for k in ('state','fault','completed_batches',
                    'discussion_observations_committed','search')}, sort_keys=True)
                if key != previous:
                    with (output/'events.jsonl').open('a', encoding='utf-8') as log:
                        log.write(json.dumps(report, ensure_ascii=False)+'\n')
                    previous = key
                if report.get('state') in TERMINAL or report.get('fault') == 'owner-exited':
                    break
                time.sleep(interval)
        finally:
            write_runtime(output/'runtime.json', dict(pid=os.getpid(), state='stopped'))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--queue', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--interval', type=int, default=15)
    args = parser.parse_args()
    watch(args.queue, args.output, args.interval)
