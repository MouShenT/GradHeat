"""Each Pika connection is used by one thread only."""
import hashlib
import json
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from gradheat.material_store import encode
from .handlers import Cancelled, PausedHuman
from .ledger import InputChanged, LeaseBusy, LeaseLost
from .messages import TASK_TYPES, decode_command

log = logging.getLogger(__name__)


def connect(url):
    import pika
    if not url:
        raise ValueError('GRADHEAT_RABBIT_URL is required')
    parameters = pika.URLParameters(url)
    parameters.heartbeat = 60
    parameters.blocked_connection_timeout = 20
    parameters.socket_timeout = 8
    parameters.stack_timeout = 20
    return pika.BlockingConnection(parameters)


def topology(channel):
    channel.exchange_declare(exchange='gradheat.commands', exchange_type='direct', durable=True)
    channel.exchange_declare(exchange='gradheat.events', exchange_type='direct', durable=True)
    channel.exchange_declare(exchange='gradheat.deadletters', exchange_type='direct', durable=True)
    for task_type in (*TASK_TYPES, 'task.status'):
        channel.queue_declare(queue='gradheat.' + task_type, durable=True, arguments={
            'x-dead-letter-exchange': 'gradheat.deadletters', 'x-dead-letter-routing-key': task_type})
        channel.queue_bind(queue='gradheat.' + task_type,
            exchange='gradheat.events' if task_type == 'task.status' else 'gradheat.commands', routing_key=task_type)
        channel.queue_declare(queue='gradheat.dead.' + task_type, durable=True)
        channel.queue_bind(queue='gradheat.dead.' + task_type, exchange='gradheat.deadletters', routing_key=task_type)


@dataclass
class Context:
    cancelled: threading.Event = field(default_factory=threading.Event)


class Processor:
    """Return only after terminal result and outbox are committed and read back."""
    def __init__(self, ledger, handlers):
        self.ledger, self.handlers = ledger, handlers

    def execute(self, command, claim, context):
        if claim.get('cancel_requested'):
            context.cancelled.set()
        try:
            payload = self.handlers.process(command, context)
            status = 'cancelled' if context.cancelled.is_set() else 'completed'
            return self.ledger.finish(command, claim['owner'], status, payload)
        except PausedHuman as error:
            return self.ledger.finish(command, claim['owner'], 'paused_human', error.payload, error.code)
        except Cancelled:
            return self.ledger.finish(command, claim['owner'], 'cancelled', {'reason': 'cancelled-before-work'}, 'cancelled')
        except (ValueError, KeyError, TimeoutError) as error:
            # Exception text may include URLs or upstream internals; persist only a controlled type.
            return self.ledger.finish(command, claim['owner'], 'failed', {'error_code': type(error).__name__, 'requires_review': True}, type(error).__name__)


class OutboxPublisher:
    def __init__(self, database, url):
        self.database, self.url = database, url

    def publish_once(self, channel):
        import pika
        sent = 0
        with self.database.connect() as con:
            with con.cursor() as cur:
                cur.execute("SELECT GET_LOCK('gradheat_python_event_outbox',0)")
                if cur.fetchone()[0] != 1:
                    con.rollback()
                    return 0
            try:
                with con.cursor() as cur:
                    cur.execute("SELECT message_id,routing_key,payload_json FROM python_event_outbox WHERE status='pending' AND next_attempt_at<=UTC_TIMESTAMP(6) ORDER BY created_at,message_id LIMIT 20 FOR UPDATE")
                    rows = cur.fetchall()
                    for mid, routing_key, raw in rows:
                        payload = json.loads(raw)
                        if payload.get('message_id') != mid or routing_key != 'task.status':
                            raise ValueError('Event outbox identity mismatch')
                        # confirm_delivery + mandatory raises for a nack or an unroutable event.
                        channel.basic_publish(exchange='gradheat.events', routing_key=routing_key,
                            body=encode(payload).encode(), mandatory=True,
                            properties=pika.BasicProperties(content_type='application/json', content_encoding='utf-8',
                                delivery_mode=2, message_id=mid, type='task.status'))
                        cur.execute("UPDATE python_event_outbox SET status='sent',sent_at=UTC_TIMESTAMP(6),attempts=attempts+1 WHERE message_id=%s AND status='pending'", (mid,))
                        sent += 1
                con.commit()
            except Exception:
                con.rollback()
                raise
            finally:
                with con.cursor() as cur:
                    cur.execute("SELECT RELEASE_LOCK('gradheat_python_event_outbox')")
        return sent

    def run(self, stop, once=False):
        failures = 0
        while not stop.is_set():
            connection = None
            try:
                connection = connect(self.url)
                channel = connection.channel()
                topology(channel)
                channel.confirm_delivery()
                while not stop.is_set():
                    self.publish_once(channel)
                    failures = 0
                    if once:
                        return
                    connection.process_data_events(time_limit=1)
            except Exception as error:
                failures += 1
                log.warning('event-publisher-unavailable type=%s', type(error).__name__)
                if once:
                    raise
                stop.wait(min(30, 2 ** min(failures, 5)))
            finally:
                if connection and connection.is_open:
                    connection.close()


class Consumer:
    def __init__(self, settings, ledger, handlers):
        self.settings, self.ledger = settings, ledger
        self.processor = Processor(ledger, handlers)
        self.stop = threading.Event()
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='gradheat-task')

    def handle(self, connection, channel, method, properties, body):
        try:
            command = decode_command(body)
            if method.routing_key != command.type or command.type not in self.settings.worker_queues:
                raise ValueError('Delivery routing does not match the worker scope')
            if getattr(properties, 'message_id', None) != str(command.message_id):
                raise ValueError('AMQP message id does not match command')
            claim = self.ledger.claim(command)
        except LeaseBusy:
            # Service heartbeats while waiting, avoiding a hot nack/requeue loop.
            until = time.monotonic() + 5
            while time.monotonic() < until:
                connection.process_data_events(time_limit=0.5)
            channel.basic_nack(delivery_tag=method.delivery_tag, requeue=True)
            return
        except (ValueError, InputChanged) as error:
            log.warning('command-rejected sha256=%s type=%s', hashlib.sha256(body).hexdigest(), type(error).__name__)
            channel.basic_reject(delivery_tag=method.delivery_tag, requeue=False)
            return
        if claim['state'] == 'duplicate':
            # Existing durable terminal result/outbox wins over redelivery; no processor call.
            channel.basic_ack(delivery_tag=method.delivery_tag)
            return
        context = Context()
        future = self.executor.submit(self.processor.execute, command, claim, context)
        heartbeat_due = time.monotonic() + 15
        try:
            while not future.done():
                # This connection and channel are touched exclusively by the consumer thread.
                connection.process_data_events(time_limit=0.5)
                if time.monotonic() >= heartbeat_due:
                    if self.ledger.heartbeat(command, claim['owner']):
                        context.cancelled.set()
                    heartbeat_due = time.monotonic() + 15
            future.result()
            # ACK is after result commit, independent readback and durable outbox.
            channel.basic_ack(delivery_tag=method.delivery_tag)
        except Exception:
            context.cancelled.set()
            # Keep a failed delivery unacknowledged. Reconnection causes redelivery;
            # the lease and deterministic frozen social batch prevent double collection.
            raise

    def run(self, once=False):
        failures = 0
        while not self.stop.is_set():
            connection = None
            try:
                connection = connect(self.settings.rabbit_url)
                channel = connection.channel()
                topology(channel)
                channel.basic_qos(prefetch_count=1)
                if once:
                    for task_type in self.settings.worker_queues:
                        method, properties, body = channel.basic_get(queue='gradheat.' + task_type, auto_ack=False)
                        if method:
                            self.handle(connection, channel, method, properties, body)
                            return True
                    return False
                for task_type in self.settings.worker_queues:
                    channel.basic_consume(queue='gradheat.' + task_type,
                        on_message_callback=lambda ch, method, props, body: self.handle(connection, ch, method, props, body), auto_ack=False)
                failures = 0
                while not self.stop.is_set():
                    connection.process_data_events(time_limit=1)
            except (KeyboardInterrupt, SystemExit):
                self.stop.set()
                raise
            except Exception as error:
                failures += 1
                log.warning('worker-unavailable type=%s', type(error).__name__)
                if once:
                    raise
                self.stop.wait(min(30, 2 ** min(failures, 5)))
            finally:
                if connection and connection.is_open:
                    connection.close()
        self.executor.shutdown(wait=True, cancel_futures=True)
