from datetime import datetime, timedelta, timezone
from pathlib import Path
import hashlib
import sys
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from gradheat_python.amqp import Consumer, Context, Processor, topology
from gradheat_python.config import Settings
from gradheat_python.handlers import PausedHuman
from gradheat_python.messages import Command, decode_command, event
from gradheat.material_store import encode


def command(**changes):
    now = datetime.now(timezone.utc)
    value = dict(schema_version=1, message_id=str(uuid4()), task_id=str(uuid4()), type='analyse.long',
        input_version='a' * 64, processor_version='gradheat-python-v1', scope={'operation': 'dashboard'},
        trace_id=str(uuid4()), attempt=1, created_at=now.isoformat(), deadline_at=(now + timedelta(minutes=15)).isoformat())
    value.update(changes)
    return Command.model_validate(value)


class FakeLedger:
    def __init__(self, events, duplicate=False, fail_commit=False):
        self.events, self.duplicate, self.fail_commit = events, duplicate, fail_commit

    def claim(self, value):
        self.events.append('claim')
        return {'state': 'duplicate'} if self.duplicate else {'state': 'claimed', 'owner': 'test'}

    def heartbeat(self, value, owner):
        self.events.append('heartbeat')
        return False

    def finish(self, value, owner, status, payload, error_code=None):
        self.events.append('persist:' + status)
        if self.fail_commit:
            raise ConnectionError('synthetic commit failure')
        self.events.append('commit-and-independent-readback')
        return {'status': status}


class Handler:
    def __init__(self, events, pause=False):
        self.events, self.pause = events, pause

    def process(self, value, context):
        self.events.append('handler')
        if self.pause:
            raise PausedHuman('platform-verification-required', {'queries_attempted': 1})
        return {'state': 'synthetic-complete'}


class Channel:
    def __init__(self, events):
        self.events = events
        self.declarations = []

    def basic_ack(self, **kwargs):
        self.events.append('ack')

    def basic_reject(self, **kwargs):
        self.events.append(('reject', kwargs['requeue']))

    def exchange_declare(self, **kwargs):
        self.declarations.append(('exchange', kwargs))

    def queue_declare(self, **kwargs):
        self.declarations.append(('queue', kwargs))

    def queue_bind(self, **kwargs):
        self.declarations.append(('bind', kwargs))


class WorkerTests(unittest.TestCase):
    def dispatch(self, ledger, handler, events, value=None):
        value = value or command()
        consumer = Consumer(Settings(worker_queues=('analyse.long',)), ledger, handler)
        channel = Channel(events)
        connection = SimpleNamespace(process_data_events=lambda **kw: None)
        method = SimpleNamespace(routing_key='analyse.long', delivery_tag=7)
        properties = SimpleNamespace(message_id=str(value.message_id))
        try:
            consumer.handle(connection, channel, method, properties, encode(value.model_dump(mode='json')).encode())
        finally:
            consumer.executor.shutdown(wait=True)

    def test_ack_after_commit_and_readback(self):
        events = []
        self.dispatch(FakeLedger(events), Handler(events), events)
        self.assertEqual(events, ['claim', 'handler', 'persist:completed', 'commit-and-independent-readback', 'ack'])

    def test_database_failure_does_not_ack(self):
        events = []
        with self.assertRaises(ConnectionError):
            self.dispatch(FakeLedger(events, fail_commit=True), Handler(events), events)
        self.assertNotIn('ack', events)

    def test_redelivery_reuses_committed_result_without_handler(self):
        events = []
        self.dispatch(FakeLedger(events, duplicate=True), Handler(events), events)
        self.assertEqual(events, ['claim', 'ack'])

    def test_human_verification_is_persisted_then_acked(self):
        events = []
        self.dispatch(FakeLedger(events), Handler(events, pause=True), events)
        self.assertEqual(events[-3:], ['persist:paused_human', 'commit-and-independent-readback', 'ack'])
        self.assertEqual(events.count('handler'), 1)

    def test_poison_routing_rejected_without_processing(self):
        events = []
        self.dispatch(FakeLedger(events), Handler(events), events, command(type='extract.documents'))
        self.assertEqual(events, [('reject', False)])

    def test_message_identity_and_private_scopes(self):
        value = command()
        self.assertEqual(decode_command(encode(value.model_dump(mode='json')).encode()), value)
        changed = value.model_copy(update={'scope': {'operation': 'heat', 'input': {'unit': '合成大学'}}})
        self.assertEqual(value.execution_key, changed.execution_key)
        self.assertNotEqual(value.input_sha, changed.input_sha)
        with self.assertRaises(ValueError):
            command(scope={'nested': {'cookies': 'forbidden'}})
        with self.assertRaises(ValueError):
            decode_command(b'{"schema_version":1,"schema_version":1}')
        with self.assertRaises(ValueError):
            decode_command(b'x' * 64001)
        paused = event(value, 'paused_human', 2, error_code='verification-required')
        self.assertEqual(paused['processor_version'], value.processor_version)
        self.assertEqual(paused['attempt'], 1)

    def test_topology_is_durable_and_poison_messages_have_deadletter_queue(self):
        channel = Channel([])
        topology(channel)
        queues = {v['queue']: v for kind, v in channel.declarations if kind == 'queue'}
        self.assertEqual(len(queues), 14)
        self.assertTrue(all(item['durable'] for item in queues.values()))
        self.assertEqual(queues['gradheat.analyse.long']['arguments']['x-dead-letter-routing-key'], 'analyse.long')
        self.assertIn('gradheat.dead.task.status', queues)


if __name__ == '__main__':
    unittest.main()
