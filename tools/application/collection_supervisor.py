"""Windows-owned collection queue supervision; monitoring never writes the database."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.request
from urllib.parse import urlsplit

from launcher import ROOT, FLAGS, exclusive_lock
from runtime_json import write_runtime

sys.path.insert(0, str(ROOT/'python_service'))
from gradheat_core.intelligence import digest
from gradheat_python.collection_status import inspect, process_alive, read_json, ProgressTracker


def private_path(value):
    path = Path(value)
    path = (ROOT/path).resolve() if not path.is_absolute() else path.resolve()
    if not path.is_relative_to((ROOT/'.research').resolve()):
        raise ValueError('Collection configuration and queues must stay private')
    return path


def load_config(path):
    config = read_json(private_path(path))
    if not isinstance(config, dict) or not isinstance(config.get('queues'), list) or not 1 <= len(config['queues']) <= 100:
        raise ValueError('An ordered list of frozen queues is required')
    queues = [private_path(value) for value in config['queues']]
    if len(set(queues)) != len(queues):
        raise ValueError('Duplicate collection queues')
    for queue in queues:
        plan = read_json(queue/'queue.json')
        if not isinstance(plan, dict) or plan.get('schema_version') != 1 or not isinstance(plan.get('batches'), list) or not 1 <= len(plan['batches']) <= 2000:
            raise ValueError('Every queue needs its existing frozen queue.json')
    hours, interval = config.get('budget_hours', 8), config.get('interval_seconds', 15)
    if isinstance(hours, bool) or not isinstance(hours, (int, float)) or not .01 <= hours <= 72:
        raise ValueError('Invalid collection budget')
    if type(interval) is not int or not 5 <= interval <= 300:
        raise ValueError('Invalid monitor interval')
    if not isinstance(config.get('python'), str) or not config['python'].strip():
        raise ValueError('An explicit collection Python runtime is required')
    return dict(config, queues=queues, budget_hours=hours, interval_seconds=interval,
                runtime_dir=private_path(config.get('runtime_dir', '.research/collection-service')))


def browser_available(port):
    """Observe the existing local CDP browser; never create or navigate a page."""
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(f'http://127.0.0.1:{port}/json/version', timeout=2) as response:
            if response.status != 200:
                return False
            metadata = json.loads(response.read(65536))
        if not isinstance(metadata, dict):
            return False
        socket = urlsplit(metadata.get('webSocketDebuggerUrl', ''))
        return socket.scheme == 'ws' and socket.hostname in {'127.0.0.1', 'localhost', '::1'}
    except (OSError, ValueError, TypeError):
        return False


def action(queue, snapshot, preceding_complete=False):
    """Never infer that a lost or uncertain checkpoint authorizes another request."""
    if not (queue/'runtime.json').exists():
        return 'ready'
    if not snapshot.get('receipt_readable'):
        return 'needs-review'
    if snapshot.get('owner_alive') is not False:
        return 'watching-existing-owner'
    if snapshot.get('current_batch') is not None:
        return 'needs-review'
    if snapshot.get('state') == 'needs-review':
        record = read_json(queue/'runtime.json') or {}
        # A never-started waiter inherited the predecessor's failure; only all
        # completed predecessors authorize its first collection. Retain the old
        # receipt and let the existing queue runner write the new ownership.
        if (preceding_complete and snapshot.get('completed_batches') == 0
                and record.get('state') == 'needs-review' and record.get('reason') == 'upstream-needs-review'
                and 'current_batch' in record and record['current_batch'] is None
                and type(record.get('processed_batches')) is int and record['processed_batches'] == 0):
            return 'ready'
        return 'needs-review'
    if snapshot.get('state') == 'queue-processed':
        return 'complete' if snapshot.get('completed_batches') == snapshot.get('total_batches') else 'needs-review'
    return 'ready' if snapshot.get('state') == 'budget-ended' else 'needs-review'


def pending_social(queue, snapshot):
    plan = read_json(queue/'queue.json')
    if not isinstance(plan, dict):
        return True
    remaining = plan['batches'][snapshot.get('completed_batches', 0):]
    return bool(remaining and remaining[0].get('social'))


def receipt_fingerprint(queue):
    return digest(read_json(queue/'runtime.json'))


def other_collector_alive():
    marker = read_json(ROOT/'.research/social/full-run-active.json')
    return isinstance(marker, dict) and marker.get('pid') is not None and process_alive(marker['pid']) is not False


def save(folder, value):
    write_runtime(folder/'runtime.json', dict(value, updated_at=datetime.now(timezone.utc).isoformat()))


def run(config_path):
    config = load_config(config_path)
    folder = config['runtime_dir']
    stop_file = folder/'stop'
    trackers, blocked = {}, {}
    child = None
    child_queue = None
    contract = read_json(ROOT/'contracts/social-collection.json') or {}
    port = contract.get('cdp_port', 9222)
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError('Invalid existing browser port')
    with exclusive_lock(folder), (folder/'collector.private.log').open('ab', buffering=0) as log:
        metadata = dict(pid=os.getpid(), state='starting', manager='Windows Task Scheduler',
                        task_name=config.get('task_name'), child_pid=None)
        while True:
            if child is not None and child.poll() is not None:
                exit_code = child.returncode
                if exit_code:
                    blocked[child_queue] = receipt_fingerprint(child_queue)
                metadata.update(child_pid=None, last_exit_code=exit_code)
                child = child_queue = None
            # Appending a future frozen queue only changes this private config.
            try:
                updated = load_config(config_path)
                if updated['runtime_dir'] != folder:
                    raise ValueError('Running collection service folder cannot change')
                config = updated
            except (OSError, ValueError, TypeError) as error:
                save(folder, dict(metadata, state='configuration-needs-review', error_type=type(error).__name__))
                if child is None and stop_file.exists():
                    break
                time.sleep(config['interval_seconds'])
                continue
            snapshots = [(queue, inspect(ROOT, queue)) for queue in config['queues']]
            reports = []
            for queue, snapshot in snapshots:
                tracker = trackers.setdefault(queue, ProgressTracker())
                reports.append(dict(queue=queue.name, **tracker.observe(snapshot, time.monotonic())))
            write_runtime(folder/'latest.json', dict(observed_at=datetime.now(timezone.utc).isoformat(), queues=reports))
            if stop_file.exists():
                metadata['state'] = 'stopping-after-current-batch' if child is not None else 'stopped'
                save(folder, metadata)
                if child is None:
                    break
            elif child is not None:
                metadata['state'] = 'collecting'
                save(folder, metadata)
            else:
                live = [queue for queue, snapshot in snapshots if action(queue, snapshot) == 'watching-existing-owner']
                if live or other_collector_alive():
                    metadata.update(state='watching-existing-owner', queue=live[0].name if live else None)
                else:
                    metadata.update(state='all-queues-processed', queue=None)
                    preceding_complete = False
                    for queue, snapshot in snapshots:
                        decision = action(queue, snapshot, preceding_complete=preceding_complete)
                        if decision == 'complete':
                            preceding_complete = True
                            continue
                        metadata['queue'] = queue.name
                        if decision != 'ready' or blocked.get(queue) == receipt_fingerprint(queue):
                            metadata['state'] = 'needs-review'
                            break
                        if pending_social(queue, snapshot) and not browser_available(port):
                            metadata['state'] = 'waiting-for-browser'
                            break
                        command = [config['python'], '-X', 'utf8', '-B', str(ROOT/'tools/research/run_collection_queue.py'),
                                   '--input', str(queue/'queue.json'), '--output', str(queue),
                                   '--hours', str(config['budget_hours']), '--stop-file', str(stop_file), '--require-cdp']
                        child = subprocess.Popen(command, cwd=ROOT, stdin=subprocess.DEVNULL,
                                                 stdout=log, stderr=log, creationflags=FLAGS)
                        child_queue = queue
                        metadata.update(state='collecting', child_pid=child.pid)
                        break
                save(folder, metadata)
            # Stop is a file request checked by the queue between batches. The
            # service never terminates, kills, or owns a kill-on-close child job.
            time.sleep(config['interval_seconds'])


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', required=True, type=Path)
    args = parser.parse_args()
    try:
        run(args.config)
        config = load_config(args.config)
        folder = config['runtime_dir']
        if (folder/'restart').exists():
            (folder/'stop').unlink(missing_ok=True)
            (folder/'restart').unlink(missing_ok=True)
            # The enabled Windows task restarts this manager after the batch.
            raise SystemExit(1)
    except Exception as error:
        folder = private_path(args.config).parent
        existing = read_json(folder/'runtime.json') or {}
        if existing.get('pid') == os.getpid() or process_alive(existing.get('pid')) is False:
            save(folder, dict(pid=os.getpid(), state='failed', error_type=type(error).__name__))
        raise SystemExit(1)
