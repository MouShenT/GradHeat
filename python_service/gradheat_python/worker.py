from . import bootstrap
import argparse
import logging
import threading

from .amqp import Consumer, OutboxPublisher
from .config import Settings
from .database import Database
from .handlers import Handlers
from .heat import HeatReader
from .ledger import ExecutionLedger
from .messages import TASK_TYPES
from .publication import PublicationReader
from .service import AnalysisService


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--once', action='store_true', help='Consume at most one available command')
    parser.add_argument('--publisher-only', action='store_true')
    args = parser.parse_args()
    settings = Settings.from_env()
    if not settings.worker_queues or set(settings.worker_queues) - set(TASK_TYPES):
        raise ValueError('Unknown worker queue binding')
    if set(settings.worker_queues)&{'collect.social.win-primary','collect.autonomous.win-primary'} and settings.worker_id != 'win-primary':
        raise ValueError('Social worker must use the dedicated Windows assignment')
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    database = Database(settings)
    publisher = OutboxPublisher(database, settings.rabbit_url)
    if args.publisher_only:
        publisher.run(threading.Event(), once=args.once)
        return
    publications = PublicationReader(database, settings)
    service = AnalysisService(publications, HeatReader(database), settings.root)
    consumer = Consumer(settings, ExecutionLedger(database, settings.worker_id, settings.lease_seconds),
        Handlers(service, database, settings))
    if args.once:
        consumer.run(once=True)
        publisher.run(threading.Event(), once=True)
        return
    thread = threading.Thread(target=publisher.run, args=(consumer.stop,), daemon=True, name='gradheat-event-publisher')
    thread.start()
    try:
        consumer.run()
    finally:
        consumer.stop.set()
        thread.join(timeout=5)


if __name__ == '__main__':
    main()
