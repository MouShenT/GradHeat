"""Worker-owned execution/result/outbox transaction; never writes app_task."""
from datetime import datetime, timedelta, timezone
import hashlib
from uuid import uuid4

from gradheat.material_store import encode
from .messages import TERMINAL, event


class LeaseBusy(RuntimeError):
    pass


class LeaseLost(RuntimeError):
    pass


class InputChanged(ValueError):
    pass


class ExecutionLedger:
    def __init__(self, database, worker_id, lease_seconds=120):
        self.database = database
        self.worker_id = worker_id
        self.lease_seconds = lease_seconds

    def _outbox(self, cur, command, status, sequence, **kw):
        item = event(command, status, sequence, **kw)
        cur.execute("INSERT INTO python_event_outbox(message_id,task_id,routing_key,payload_json,status,attempts,next_attempt_at,created_at) VALUES(%s,%s,%s,%s,'pending',0,UTC_TIMESTAMP(6),UTC_TIMESTAMP(6))",
            (item['message_id'], item['task_id'], 'task.status', encode(item)))

    def claim(self, command):
        owner = self.worker_id + ':' + uuid4().hex
        if len(owner) > 100:
            raise ValueError('Worker id too long')
        with self.database.connect() as con:
            try:
                with con.cursor() as cur:
                    # A command is accepted only if the Java-owned immutable task matches it.
                    cur.execute('SELECT task_type,input_version,processor_version,scope_json,attempt,cancel_requested FROM app_task WHERE task_id=%s', (str(command.task_id),))
                    task = cur.fetchone()
                    if task is None:
                        raise InputChanged('Task does not exist in Java task ledger')
                    import json
                    if (task[0] != command.type or task[1] != command.input_version or task[2] != command.processor_version
                            or encode(json.loads(task[3])) != encode(command.scope) or task[4] != command.attempt):
                        raise InputChanged('Command does not match the Java task ledger')
                    cur.execute("INSERT IGNORE INTO python_worker_execution(execution_key,task_id,input_version,input_sha,processor_version,attempt,status,lease_owner,lease_until,updated_at) VALUES(%s,%s,%s,%s,%s,%s,'ready','',UTC_TIMESTAMP(6),UTC_TIMESTAMP(6))",
                        (command.execution_key, str(command.task_id), command.input_version, command.input_sha, command.processor_version, command.attempt))
                    cur.execute('SELECT status,lease_until,input_sha,result_id,result_sha FROM python_worker_execution WHERE execution_key=%s FOR UPDATE', (command.execution_key,))
                    row = cur.fetchone()
                    if row[2] != command.input_sha:
                        raise InputChanged('An immutable execution input changed')
                    if row[0] in TERMINAL:
                        cur.execute('SELECT result_bytes,result_sha FROM python_worker_result WHERE result_id=%s AND execution_key=%s', (row[3], command.execution_key))
                        result = cur.fetchone()
                        if not result or hashlib.sha256(result[0]).hexdigest() != row[4] or result[1] != row[4]:
                            raise ValueError('Duplicate execution has an invalid stored result')
                        cur.execute("SELECT COUNT(*) FROM python_event_outbox WHERE task_id=%s AND JSON_EXTRACT(payload_json,'$.attempt')=%s AND JSON_EXTRACT(payload_json,'$.sequence')=2 AND JSON_UNQUOTE(JSON_EXTRACT(payload_json,'$.result_id'))=%s", (str(command.task_id), command.attempt, row[3]))
                        if not cur.fetchone()[0]:
                            raise ValueError('Duplicate execution is missing its durable terminal event')
                        con.commit()
                        return dict(state='duplicate', status=row[0], result_id=row[3], result_sha=row[4])
                    if row[0] == 'running':
                        cur.execute('SELECT lease_until>UTC_TIMESTAMP(6) FROM python_worker_execution WHERE execution_key=%s', (command.execution_key,))
                        if cur.fetchone()[0]:
                            raise LeaseBusy('Another worker owns an active lease')
                    cur.execute("UPDATE python_worker_execution SET status='running',lease_owner=%s,lease_until=DATE_ADD(UTC_TIMESTAMP(6),INTERVAL %s SECOND),updated_at=UTC_TIMESTAMP(6) WHERE execution_key=%s",
                        (owner, self.lease_seconds, command.execution_key))
                    self._outbox(cur, command, 'running', 1)
                con.commit()
                return dict(state='claimed', owner=owner, cancel_requested=bool(task[5]))
            except Exception:
                con.rollback()
                raise

    def heartbeat(self, command, owner):
        with self.database.connect() as con:
            with con.cursor() as cur:
                cur.execute("UPDATE python_worker_execution SET lease_until=DATE_ADD(UTC_TIMESTAMP(6),INTERVAL %s SECOND),updated_at=UTC_TIMESTAMP(6) WHERE execution_key=%s AND lease_owner=%s AND status='running' AND lease_until>UTC_TIMESTAMP(6)",
                    (self.lease_seconds, command.execution_key, owner))
                if cur.rowcount != 1:
                    raise LeaseLost('Worker lease lost; do not acknowledge')
                cur.execute('SELECT cancel_requested,attempt FROM app_task WHERE task_id=%s', (str(command.task_id),))
                task = cur.fetchone()
                if task is None or task[1] != command.attempt:
                    raise LeaseLost('Task attempt changed')
            con.commit()
            return bool(task[0])

    def finish(self, command, owner, status, payload, error_code=None):
        if status not in TERMINAL:
            raise ValueError('Unsupported terminal worker status')
        canonical = encode(payload)
        if len(canonical.encode()) > 4_000_000:
            raise ValueError('Task result exceeds persistence budget')
        result_id = str(uuid4())
        sha = hashlib.sha256(canonical.encode()).hexdigest()
        with self.database.connect() as con:
            try:
                with con.cursor() as cur:
                    cur.execute("SELECT status,lease_owner,lease_until>UTC_TIMESTAMP(6) FROM python_worker_execution WHERE execution_key=%s FOR UPDATE", (command.execution_key,))
                    row = cur.fetchone()
                    if row is None or row[0] != 'running' or row[1] != owner or not row[2]:
                        raise LeaseLost('Cannot commit result after ownership loss')
                    cur.execute('INSERT INTO python_worker_result(result_id,execution_key,payload_json,result_bytes,result_sha,created_at) VALUES(%s,%s,%s,%s,%s,UTC_TIMESTAMP(6))',
                        (result_id, command.execution_key, canonical, canonical.encode(), sha))
                    cur.execute('UPDATE python_worker_execution SET status=%s,result_id=%s,result_sha=%s,error_code=%s,updated_at=UTC_TIMESTAMP(6) WHERE execution_key=%s',
                        (status, result_id, sha, error_code, command.execution_key))
                    public_status = 'succeeded' if status == 'completed' else status
                    self._outbox(cur, command, public_status, 2, result_id=result_id, result_sha=sha, error_code=error_code)
                con.commit()
            except Exception:
                con.rollback()
                raise
        # Independent read transaction catches byte/JSON mismatch before delivery ACK.
        with self.database.connect() as con:
            with con.cursor() as cur:
                cur.execute('SELECT result_bytes,result_sha FROM python_worker_result WHERE result_id=%s', (result_id,))
                row = cur.fetchone()
                if not row or hashlib.sha256(row[0]).hexdigest() != sha or row[0] != canonical.encode() or row[1] != sha:
                    raise ValueError('Committed result readback mismatch')
            con.rollback()
        return dict(status=status, result_id=result_id, result_sha=sha)
