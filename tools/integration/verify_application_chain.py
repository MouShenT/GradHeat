"""Bounded, explicit live acceptance of Java -> Rabbit -> Python -> MySQL.

No admission facts, publication heads or personal comparisons are written. Only
new UUID-namespaced analysis task audit rows are retained. Credentials are read
privately, passed in child environments, and never included in the report.
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack
from datetime import datetime, timezone
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import subprocess
import sys
import time
from urllib.parse import quote
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
for folder in (ROOT / 'crawler', ROOT / 'python_service'):
    sys.path.insert(0, str(folder))

import httpx
import pymysql
from gradheat.db import _load_env
from gradheat.material_store import encode
from gradheat.vm_connection import ssh_connection
from gradheat_python.amqp import connect, topology


def private_env(path):
    result = {}
    for line in path.read_text(encoding='utf-8-sig').splitlines():
        if not line.strip() or line.lstrip().startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        result[key.strip()] = value.strip().strip('"').strip("'")
    return result


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def terminate(process):
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=8)


def wait_for(predicate, label, timeout=45):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        value = predicate()
        if value:
            return value
        time.sleep(.25)
    raise TimeoutError(label)


def public_projection(value):
    """Source details belong to the database, not browser responses."""
    forbidden = {'source_url', 'source_urls', 'raw_path', 'source_path',
        'artifact', 'original_sha256', 'transcription_sha256', 'cookie',
        'cookies', 'authorization', 'password', 'signature', 'private_log', 'har'}
    if isinstance(value, dict):
        return not (forbidden & {str(key).lower() for key in value}) and all(public_projection(item) for item in value.values())
    if isinstance(value, list):
        return all(public_projection(item) for item in value)
    return True


class Acceptance:
    def __init__(self, report_dir):
        self.folder = report_dir
        self.checks = []
        self.task_ids = []
        self.env = os.environ.copy()
        self.started_at = datetime.now(timezone.utc).isoformat()
        self.client = httpx.Client(timeout=25, trust_env=False)
        self.report = dict(started_at=self.started_at, checks=self.checks,
            task_ids=self.task_ids, writes='analysis-task-audit-only',
            browser_collection=False, personal_comparison_writes=False,
            publication_head_writes=False)

    def check(self, name, condition, **details):
        self.checks.append(dict(name=name, passed=bool(condition), **details))
        if not condition:
            raise AssertionError(name)

    def db(self):
        return pymysql.connect(host='127.0.0.1', port=self.db_port,
            user=self.cfg.get('GRADHEAT_DB_USER', 'gradheat'),
            password=self.cfg['GRADHEAT_DB_PASSWORD'],
            database=self.cfg.get('GRADHEAT_DB_NAME', 'gradheat'),
            charset='utf8mb4', autocommit=False, connect_timeout=8,
            read_timeout=25, write_timeout=25)

    def rows(self, query, params=()):
        with self.db() as con:
            with con.cursor() as cur:
                cur.execute(query, params)
                return cur.fetchall()

    def request(self, method, route, data=None, token=True):
        headers = {'Authorization': 'Bearer ' + self.api_token} if token else {}
        return self.client.request(method, self.java_url + route, json=data, headers=headers)

    def launch(self, stack, name, command, env):
        output = stack.enter_context((self.folder / (name + '.private.log')).open('wb'))
        process = subprocess.Popen(command, cwd=ROOT, env=env,
            stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        stack.callback(terminate, process)
        return process

    def ready(self, process, url, headers=None):
        if process.poll() is not None:
            raise RuntimeError('Owned test process exited before readiness')
        try:
            response = self.client.get(url, headers=headers or {})
            return response if response.status_code == 200 else False
        except httpx.HTTPError:
            return False

    def worker_once(self, stack, name):
        worker = self.launch(stack, name,
            [sys.executable, '-X', 'utf8', '-B', '-m', 'gradheat_python.worker', '--once'], self.env)
        try:
            code = worker.wait(timeout=70)
        except subprocess.TimeoutExpired:
            terminate(worker)
            raise TimeoutError('Bounded one-message worker')
        self.check(name + '-exit', code == 0)

    def task(self, scope):
        body = dict(request_id=str(uuid4()), type='analyse.long',
            input_version=self.version, scope=scope, deadline_minutes=10)
        response = self.request('POST', '/api/v1/tasks', body)
        self.check('task-create-202', response.status_code == 202)
        task_id = response.json()['task_id']
        self.task_ids.append(task_id)
        return task_id, body

    def task_state(self, task_id):
        response = self.request('GET', '/api/v1/tasks/' + task_id)
        response.raise_for_status()
        return response.json()

    def published(self, task_id):
        rows = self.rows('SELECT status,payload_json FROM app_outbox WHERE task_id=%s', (task_id,))
        return rows[0][1] if rows and rows[0][0] == 'sent' else False

    def queue_count(self, channel):
        return channel.queue_declare(queue='gradheat.analyse.long', passive=True).method.message_count

    def publish(self, channel, exchange, routing_key, raw, message_id):
        import pika
        channel.basic_publish(exchange=exchange, routing_key=routing_key, body=raw,
            mandatory=True, properties=pika.BasicProperties(content_type='application/json',
            content_encoding='utf-8', delivery_mode=2, message_id=message_id))

    def run(self):
        self.folder.mkdir(parents=True, exist_ok=True)
        self.cfg = _load_env()
        infra = private_env(ROOT / 'infra/docker/.env')
        self.internal_token = secrets.token_urlsafe(40)
        self.api_token = secrets.token_urlsafe(40)
        ssh, target = ssh_connection()
        inspect = subprocess.run(ssh + [target,
            "sudo -n docker inspect gradheat-mysql gradheat-rabbitmq gradheat-redis --format '{{.Name}} {{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}'"],
            capture_output=True, text=True, timeout=18, check=True,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        addresses = {}
        for line in inspect.stdout.splitlines():
            name, address = line.split()
            addresses[name.lstrip('/')] = str(ipaddress.ip_address(address))
        self.db_port, rabbit_port, redis_port, python_port, java_port = [free_port() for _ in range(5)]
        self.java_url = f'http://127.0.0.1:{java_port}'
        python_url = f'http://127.0.0.1:{python_port}'
        rabbit_url = 'amqp://{}:{}@127.0.0.1:{}/{}'.format(
            quote(infra['RABBITMQ_USER'], safe=''), quote(infra['RABBITMQ_PASSWORD'], safe=''), rabbit_port, quote('/gradheat', safe=''))
        self.env.update(GRADHEAT_DB_MODE='direct', GRADHEAT_DB_HOST='127.0.0.1',
            GRADHEAT_DB_PORT=str(self.db_port), GRADHEAT_DB_NAME=self.cfg.get('GRADHEAT_DB_NAME', 'gradheat'),
            GRADHEAT_DB_USER=self.cfg.get('GRADHEAT_DB_USER', 'gradheat'),
            GRADHEAT_DB_PASSWORD=self.cfg['GRADHEAT_DB_PASSWORD'],
            GRADHEAT_INTERNAL_TOKEN=self.internal_token, GRADHEAT_API_TOKEN=self.api_token,
            GRADHEAT_BIND_HOST='127.0.0.1', GRADHEAT_PYTHON_PORT=str(python_port),
            GRADHEAT_BIND_ADDRESS='127.0.0.1', GRADHEAT_JAVA_PORT=str(java_port),
            GRADHEAT_MYSQL_URL=f'jdbc:mysql://127.0.0.1:{self.db_port}/{self.cfg.get("GRADHEAT_DB_NAME", "gradheat")}?connectionTimeZone=UTC&forceConnectionTimeZoneToSession=true&characterEncoding=UTF-8',
            GRADHEAT_MYSQL_USER=self.cfg.get('GRADHEAT_DB_USER', 'gradheat'),
            GRADHEAT_MYSQL_PASSWORD=self.cfg['GRADHEAT_DB_PASSWORD'],
            GRADHEAT_PYTHON_URL=python_url, GRADHEAT_PUBLIC_WRITE_ENABLED='false',
            GRADHEAT_MESSAGING_ENABLED='true', GRADHEAT_RABBIT_HOST='127.0.0.1',
            GRADHEAT_RABBIT_PORT=str(rabbit_port), GRADHEAT_RABBIT_USER=infra['RABBITMQ_USER'],
            GRADHEAT_RABBIT_PASSWORD=infra['RABBITMQ_PASSWORD'], GRADHEAT_RABBIT_VHOST='/gradheat',
            GRADHEAT_RABBIT_URL=rabbit_url, GRADHEAT_WORKER_ID='integration-analysis',
            GRADHEAT_WORKER_QUEUES='analyse.long', GRADHEAT_REDIS_ENABLED='true',
            GRADHEAT_REDIS_HOST='127.0.0.1', GRADHEAT_REDIS_PORT=str(redis_port),
            GRADHEAT_REDIS_PASSWORD=infra['REDIS_PASSWORD'], PYTHONPATH=str(ROOT / 'python_service'))
        java = shutil.which('java')
        jar = ROOT / 'backend/target/gradheat-backend-0.1.0.jar'
        if not java or not jar.is_file():
            raise RuntimeError('Build Java jar and configure JDK before live acceptance')
        with ExitStack() as stack:
            stack.callback(self.client.close)
            tunnel = self.launch(stack, 'ssh-tunnel', ssh + ['-o', 'ExitOnForwardFailure=yes',
                '-o', 'ServerAliveInterval=30', '-N',
                '-L', f'127.0.0.1:{self.db_port}:{addresses["gradheat-mysql"]}:3306',
                '-L', f'127.0.0.1:{rabbit_port}:{addresses["gradheat-rabbitmq"]}:5672',
                '-L', f'127.0.0.1:{redis_port}:{addresses["gradheat-redis"]}:6379', target], self.env)
            def tunnel_ready():
                if tunnel.poll() is not None:
                    raise RuntimeError('Strict SSH tunnel failed')
                try:
                    with socket.create_connection(('127.0.0.1', self.db_port), timeout=.2):
                        return True
                except OSError:
                    return False
            wait_for(tunnel_ready, 'SSH tunnel readiness', 10)
            before_head = self.rows("SELECT version_id FROM admissions_head WHERE name='current'")[0][0]
            before_comparisons = self.rows('SELECT comparison_id,result_json,report_md,result_bytes FROM personal_comparison ORDER BY comparison_id')
            self.version = before_head
            connection = connect(rabbit_url)
            stack.callback(connection.close)
            channel = connection.channel()
            topology(channel)
            channel.confirm_delivery()
            # Never consume pre-existing jobs or deliver another operator's outbox.
            self.check('analysis-queue-empty-before-test', self.queue_count(channel) == 0)
            self.check('no-preexisting-java-outbox-pending', self.rows("SELECT COUNT(*) FROM app_outbox WHERE status IN ('pending','publishing')")[0][0] == 0)
            self.check('no-preexisting-python-event-pending', self.rows("SELECT COUNT(*) FROM python_event_outbox WHERE status='pending'")[0][0] == 0)
            python = self.launch(stack, 'python-api', [sys.executable, '-X', 'utf8', '-B', '-m', 'gradheat_python.api'], self.env)
            py_headers = {'X-GradHeat-Internal-Token': self.internal_token}
            wait_for(lambda: self.ready(python, python_url + '/internal/v1/ready', py_headers), 'Python database readiness')
            self.check('python-private-api-rejects-missing-token', self.client.get(python_url + '/internal/v1/dashboard').status_code == 401)
            java_process = self.launch(stack, 'java-api', [java, '-jar', str(jar)], self.env)
            wait_for(lambda: self.ready(java_process, self.java_url + '/api/v1/version'), 'Java database readiness', 60)
            admissions = self.request('GET', '/api/v1/admissions')
            self.check('java-admissions-version', admissions.status_code == 200 and admissions.headers.get('X-Data-Version') == self.version)
            payload = admissions.json()
            self.check('admissions-source-free-public-projection', public_projection(payload))
            self.check('public-payload-exact-sha', hashlib.sha256(encode(payload).encode()).hexdigest() == self.version)
            self.check('repeat-java-cache-read', self.request('GET', '/api/v1/admissions').json() == payload)
            programme_ids = [p['id'] for p in payload['programmes'] if p.get('year') == 2027 and p.get('eligible_11408') is True][:2]
            self.check('two-current-11408-candidates-available', len(programme_ids) == 2)
            recommendation = dict(data_version=self.version, limit=3)
            direct_recommendation = self.client.post(python_url + '/internal/v1/recommendations', json=recommendation, headers=py_headers)
            self.check('direct-python-no-score-recommendation', direct_recommendation.status_code == 200,
                status_code=direct_recommendation.status_code)
            recommend_response = self.request('POST', '/api/v1/recommendations', recommendation)
            self.check('java-python-no-score-recommendation', recommend_response.status_code == 200 and recommend_response.json().get('data_version') == self.version,
                status_code=recommend_response.status_code, response_code=recommend_response.json().get('code'))
            self.check('recommendation-source-free-public-projection', public_projection(recommend_response.json()))
            stale = self.request('POST', '/api/v1/recommendations', dict(recommendation, data_version='0' * 64))
            self.check('stale-request-409', stale.status_code == 409)
            scenario = dict(data_version=self.version, participants=12, crowding_weight=2, seed=7,
                options=[dict(programme_id=pid, capacity=8, preference=6 + i) for i, pid in enumerate(programme_ids)])
            sync_game = self.request('POST', '/api/v1/game-scenario', scenario)
            self.check('sync-game-java-python', sync_game.status_code == 200 and sync_game.json()['base']['converged'])
            comparison = dict(title='临时模块合同验收，不保存个人比较', data_version=self.version,
                candidates=[dict(programme_id=pid) for pid in programme_ids])
            internal_compare = self.client.post(python_url + '/internal/v1/comparisons/evaluate', json=comparison, headers=py_headers)
            self.check('python-compare-canonical-contract', internal_compare.status_code == 200)
            packed = internal_compare.json()
            self.check('comparison-archive-byte-sha', hashlib.sha256(packed['canonical_archive'].encode()).hexdigest() == packed['comparison_id'])
            self.check('comparison-archive-payload', json.loads(packed['canonical_archive']) == dict(result=packed['result'], report_md=packed['report_md']))
            self.check('comparison-exact-result-text', packed['canonical_result'] == encode(packed['result']))
            public_compare = self.request('POST', '/api/v1/admissions/compare', comparison)
            self.check('java-compare-unwrapped', public_compare.status_code == 200 and public_compare.json() == packed['result'])
            self.check('write-requires-bearer', self.request('POST', '/api/v1/tasks', {}, token=False).status_code == 403)
            task_id, task_body = self.task(dict(operation='game-scenario', input=scenario))
            same = self.request('POST', '/api/v1/tasks', task_body)
            self.check('request-id-idempotent', same.status_code == 202 and same.json().get('reused') is True)
            changed = dict(task_body, scope=dict(operation='dashboard', input={}))
            self.check('request-id-changed-scope-409', self.request('POST', '/api/v1/tasks', changed).status_code == 409)
            raw_command = wait_for(lambda: self.published(task_id), 'Java confirmed command outbox')
            self.worker_once(stack, 'worker-first')
            completed = wait_for(lambda: (state if (state := self.task_state(task_id))['status'] == 'succeeded' else False), 'Java terminal event consumption')
            self.check('java-rabbit-python-mysql-java-success', completed['last_event_sequence'] == 2 and completed['result_sha'] is not None)
            result_response = self.request('GET', '/api/v1/tasks/' + task_id + '/result')
            self.check('async-sync-result-equal', result_response.status_code == 200 and result_response.json() == sync_game.json())
            stored = self.rows('SELECT r.result_bytes,r.result_sha FROM python_worker_result r JOIN python_worker_execution e ON e.execution_key=r.execution_key WHERE e.task_id=%s', (task_id,))
            self.check('one-worker-result-exact-bytes', len(stored) == 1 and hashlib.sha256(stored[0][0]).hexdigest() == stored[0][1] == completed['result_sha'])
            self.check('result-bytes-parse-equal', json.loads(stored[0][0]) == result_response.json())
            command = json.loads(raw_command)
            self.publish(channel, 'gradheat.commands', 'analyse.long', encode(command).encode(), command['message_id'])
            self.worker_once(stack, 'worker-duplicate')
            duplicate_results = self.rows('SELECT COUNT(*) FROM python_worker_result r JOIN python_worker_execution e ON e.execution_key=r.execution_key WHERE e.task_id=%s', (task_id,))[0][0]
            self.check('duplicate-command-not-reexecuted', duplicate_results == 1 and self.queue_count(channel) == 0)
            dead_before = channel.queue_declare(queue='gradheat.dead.analyse.long', passive=True).method.message_count
            altered = dict(command, scope=dict(operation='dashboard', input={}))
            self.publish(channel, 'gradheat.commands', 'analyse.long', encode(altered).encode(), altered['message_id'])
            self.worker_once(stack, 'worker-altered-scope')
            self.check('altered-immutable-command-deadlettered',
                channel.queue_declare(queue='gradheat.dead.analyse.long', passive=True).method.message_count == dead_before + 1)
            self.check('altered-command-not-reexecuted', self.rows('SELECT COUNT(*) FROM python_worker_result r JOIN python_worker_execution e ON e.execution_key=r.execution_key WHERE e.task_id=%s', (task_id,))[0][0] == 1)
            event_rows = self.rows("SELECT payload_json FROM python_event_outbox WHERE task_id=%s AND JSON_EXTRACT(payload_json,'$.sequence')=2", (task_id,))
            terminal = json.loads(event_rows[0][0])
            before_inbox = self.rows('SELECT COUNT(*) FROM app_inbox WHERE task_id=%s', (task_id,))[0][0]
            self.publish(channel, 'gradheat.events', 'task.status', encode(terminal).encode(), terminal['message_id'])
            time.sleep(1)
            self.check('duplicate-event-inbox-idempotent', self.rows('SELECT COUNT(*) FROM app_inbox WHERE task_id=%s', (task_id,))[0][0] == before_inbox and self.task_state(task_id)['status'] == 'succeeded')
            late = dict(terminal, message_id=str(uuid4()), status='running', sequence=1, result_id=None, result_sha=None)
            self.publish(channel, 'gradheat.events', 'task.status', encode(late).encode(), late['message_id'])
            disposition = wait_for(lambda: (rows[0][0] if (rows := self.rows('SELECT disposition FROM app_inbox WHERE message_id=%s', (late['message_id'],))) else False), 'Late event retained as stale')
            self.check('late-event-does-not-regress', disposition == 'stale' and self.task_state(task_id)['status'] == 'succeeded')
            cancel_id, _ = self.task(dict(operation='dashboard', input={}))
            wait_for(lambda: self.published(cancel_id), 'Cancellation test command published')
            cancelled_request = self.request('POST', '/api/v1/tasks/' + cancel_id + '/cancel')
            self.check('cancel-request-persisted-before-worker', cancelled_request.status_code == 200 and cancelled_request.json()['cancel_requested'])
            self.worker_once(stack, 'worker-cancel')
            cancel_state = wait_for(lambda: (state if (state := self.task_state(cancel_id))['status'] == 'cancelled' else False), 'Cooperative cancellation event')
            cancel_result = json.loads(self.rows('SELECT r.payload_json FROM python_worker_result r JOIN python_worker_execution e ON e.execution_key=r.execution_key WHERE e.task_id=%s', (cancel_id,))[0][0])
            self.check('worker-honours-cancel-before-analysis', cancel_state['last_event_sequence'] == 2 and cancel_result == {'reason': 'cancelled-before-work'})
            self.check('publication-head-unchanged', self.rows("SELECT version_id FROM admissions_head WHERE name='current'")[0][0] == before_head)
            self.check('personal-comparisons-unchanged', self.rows('SELECT comparison_id,result_json,report_md,result_bytes FROM personal_comparison ORDER BY comparison_id') == before_comparisons)
            self.check('owned-analysis-queue-drained', self.queue_count(channel) == 0)
            self.report['ports'] = dict(java=java_port, python=python_port)
        self.report['owned_processes_closed'] = True

    def save(self, error=None):
        self.report.update(completed_at=datetime.now(timezone.utc).isoformat(),
            passed=error is None and all(c['passed'] for c in self.checks),
            check_count=len(self.checks), error_type=type(error).__name__ if error else None)
        self.folder.mkdir(parents=True, exist_ok=True)
        (self.folder / 'verification.json').write_text(json.dumps(self.report, ensure_ascii=False, indent=2), encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true', help='Authorize bounded live infrastructure tests and analysis audit rows')
    args = parser.parse_args()
    if not args.live:
        parser.error('Live test requires explicit --live; no infrastructure is contacted by default')
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    acceptance = Acceptance(ROOT / '.research/module-integration-20261009' / stamp)
    try:
        acceptance.run()
    except Exception as error:
        acceptance.save(error)
        # Do not print exceptions that could embed a connection URL or credentials.
        print(encode(dict(passed=False, error_type=type(error).__name__,
            last_check=acceptance.checks[-1]['name'] if acceptance.checks else None,
            report=(acceptance.folder / 'verification.json').relative_to(ROOT).as_posix())))
        raise SystemExit(1)
    acceptance.save()
    print(encode(dict(passed=True, checks=len(acceptance.checks),
        report=(acceptance.folder / 'verification.json').relative_to(ROOT).as_posix())))


if __name__ == '__main__':
    main()
