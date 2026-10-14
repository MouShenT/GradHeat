"""Read-only, bounded progress from the existing frozen collection receipts."""
from collections import Counter
from datetime import datetime, timezone
import ctypes
import json
import os
from pathlib import Path

from gradheat_core.intelligence import digest

TERMINAL = {'budget-ended', 'queue-processed', 'needs-review'}
PHASES = TERMINAL | {'running', 'collecting', 'collecting-search', 'search-stage-ended','waiting-for-existing-queue'}
STATES = {'running', 'retained', 'needs-review', 'needs-human', 'unavailable-at-check'}


def process_alive(pid):
    if type(pid) is not int or not 0 < pid <= 0xffffffff:
        return False
    if os.name == 'nt':
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
        kernel.OpenProcess.restype = ctypes.c_void_p
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        kernel.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return None if ctypes.get_last_error() == 5 else False
        try:
            code = ctypes.c_ulong()
            return code.value == 259 if kernel.GetExitCodeProcess(handle, ctypes.byref(code)) else None
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except PermissionError:
        return None
    except ProcessLookupError:
        return False


def read_json(path):
    try:
        if path.stat().st_size > 25_000_000:
            return None
        return json.loads(path.read_text(encoding='utf-8-sig'))
    except (OSError, ValueError):
        # A producer's non-atomic search checkpoint can briefly be incomplete.
        return None


def count(value):
    return value if type(value) is int and 0 <= value <= 100_000_000 else 0


def inspect(root, folder, alive=process_alive):
    folder = Path(folder).resolve()
    if not folder.is_relative_to((Path(root)/'.research').resolve()):
        raise ValueError('Only private project queues may be monitored')
    runtime, plan = read_json(folder/'runtime.json'), read_json(folder/'queue.json')
    if not isinstance(runtime, dict) or not isinstance(plan, dict):
        return {'state': 'receipt-unavailable', 'receipt_readable': False}
    batches = plan.get('batches')
    if plan.get('schema_version') != 1 or not isinstance(batches, list) or not 1 <= len(batches) <= 2000 or runtime.get('queue_sha') != digest(plan):
        return {'state': 'identity-mismatch', 'receipt_readable': False}
    total, completed = len(batches), count(runtime.get('processed_batches'))
    current = runtime.get('current_batch')
    if completed > total or current is not None and (type(current) is not int or not 0 <= current < total):
        return {'state': 'identity-mismatch', 'receipt_readable': False}
    phase = runtime.get('state')
    if phase not in PHASES:
        return {'state': 'identity-mismatch', 'receipt_readable': False}
    observations = 0; committed = 0; websites = 0
    platform_counts = Counter()
    for index in range(completed):
        batch = batches[index]
        path = folder/f'batch-{index:04d}-{digest(batch)[:12]}'
        report = read_json(path/'report.json')
        original_input = read_json(path/'input.json')
        if not isinstance(report, dict) or original_input != batch:
            return {'state': 'receipt-unavailable', 'receipt_readable': False}
        receipts = report.get('receipts', [])
        if not isinstance(receipts, list):
            return {'state': 'identity-mismatch', 'receipt_readable': False}
        for receipt in receipts:
            if not isinstance(receipt, dict) or receipt.get('database_state') != 'committed':
                continue
            committed += 1
            if receipt.get('type') == 'social' and receipt.get('platform') in {'bili','xhs','zhihu','dy'}:
                size = count(receipt.get('snapshots'))
                observations += size; platform_counts[receipt['platform']] += size
            elif receipt.get('type') == 'website':
                websites += 1
    states = Counter(); planned = 0
    if current is not None:
        batch = batches[current]
        planned = len(batch.get('social', []))+len(batch.get('websites', []))
        retrieval = read_json(folder/f'batch-{current:04d}-{digest(batch)[:12]}'/'retrieval.json')
        if isinstance(retrieval, dict):
            for row in retrieval.values():
                if isinstance(row, dict) and row.get('state') in STATES:
                    states[row['state']] += 1
    search = read_json(folder/'search/report.json')
    search_counts = {}
    if isinstance(search, dict):
        for source, target in [('queried_keywords','queried'),('not_indexed','not_indexed'),('insufficient','insufficient'),('signals','signals_collected')]:
            rows = search.get(source)
            search_counts[target] = len(rows) if isinstance(rows, list) else 0
        search_counts['import_completed'] = runtime.get('search_exit_code') == 0 and phase != 'collecting-search'
        search_counts['state'] = search.get('state') if search.get('state') in {'running','collected','no-indexed-keywords','needs-human-or-provider-change'} else 'unknown'
        if search_counts['state'] == 'needs-human-or-provider-change':
            code = search.get('error_code')
            search_counts['error_code'] = code if type(code) is int else None
    owner = alive(runtime.get('pid'))
    return dict(state=phase, receipt_readable=True, owner_alive=owner, completed_batches=completed,
        total_batches=total, current_batch=current, current_planned_tasks=planned,
        current_task_states=dict(states), committed_tasks=committed,
        discussion_observations_committed=observations, platform_observations=dict(platform_counts),
        websites_committed=websites, search=search_counts,
        fault='owner-exited' if owner is False and phase not in TERMINAL else None)


class ProgressTracker:
    def __init__(self, stall_seconds=900):
        self.signature = None; self.last_progress = None; self.last_good = None
        self.stall_seconds = stall_seconds
        self.unreadable_since = None

    def observe(self, snapshot, clock):
        if not snapshot.get('receipt_readable'):
            if self.unreadable_since is None:
                self.unreadable_since = clock
            return dict(snapshot, last_good_progress=self.last_good,
                fault='receipt-unreadable' if clock-self.unreadable_since >= self.stall_seconds else None,
                observed_at=datetime.now(timezone.utc).isoformat())
        self.unreadable_since = None
        progress = {k: snapshot.get(k) for k in ('state','completed_batches','current_batch','current_task_states',
            'committed_tasks','discussion_observations_committed','websites_committed','search')}
        signature = digest(progress)
        if signature != self.signature:
            self.signature = signature; self.last_progress = clock
        elapsed = max(0, clock-self.last_progress)
        fault = snapshot.get('fault')
        if not fault and snapshot['state'] not in TERMINAL | {'waiting-for-existing-queue'} and snapshot.get('owner_alive') is True and elapsed >= self.stall_seconds:
            fault = 'no-new-receipt'
        result = dict(snapshot, fault=fault, seconds_without_progress=round(elapsed),
            observed_at=datetime.now(timezone.utc).isoformat())
        self.last_good = progress
        return result
