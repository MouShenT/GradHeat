"""Apply only the additive application migration; never replay the old schema."""
import argparse
import hashlib
import json
from pathlib import Path
from gradheat.db import connect, _split_statements
from gradheat.vm_db import connect_vm
from gradheat.publication_bytes import backfill

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / 'crawler/sql/009_application_messaging.sql'


def migrate_application(con):
    checksum = hashlib.sha256(MIGRATION.read_bytes()).hexdigest()
    with con.cursor() as cur:
        cur.execute("SELECT GET_LOCK('gradheat_application_migration',10)")
        if cur.fetchone()[0] != 1:
            raise RuntimeError('Application migration already running')
    try:
        with con.cursor() as cur:
            cur.execute('SELECT checksum FROM research_schema_migration WHERE migration_id=%s', (MIGRATION.name,))
            prior = cur.fetchone()
            if prior:
                if prior[0] != checksum:
                    raise ValueError('Applied application migration checksum changed')
                return {'migration': MIGRATION.name, 'state': 'already-applied', 'checksum': checksum}
            statements = _split_statements(MIGRATION.read_text(encoding='utf-8'))
            if not statements or any(not stmt.lstrip().upper().startswith('CREATE TABLE IF NOT EXISTS ') for stmt in statements):
                raise ValueError('Application migration must contain additive tables only')
            # MySQL DDL autocommits; IF NOT EXISTS permits a failed creation to resume.
            # Record its checksum only when every table has been created.
            for statement in statements:
                cur.execute(statement)
            cur.execute('INSERT INTO research_schema_migration(migration_id,checksum) VALUES(%s,%s)', (MIGRATION.name,checksum))
        con.commit()
        return {'migration': MIGRATION.name, 'state': 'applied', 'checksum': checksum}
    finally:
        with con.cursor() as cur:
            cur.execute("SELECT RELEASE_LOCK('gradheat_application_migration')")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--vm', action='store_true', help='Use the previously trusted SSH VM connection')
    parser.add_argument('--backfill', action='store_true', help='Verify and archive existing publication bytes')
    args = parser.parse_args()
    manager = connect_vm(ROOT / '.research/application-migration') if args.vm else connect()
    with manager as con:
        report = migrate_application(con)
        if args.backfill:
            report['byte_archive'] = backfill(con)
        print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    main()
