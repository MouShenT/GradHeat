"""Immutable personal comparisons in MySQL, bound to their data publication."""
import hashlib
import json
import sys

from .sessions import canonical
from .admissions_decision import render_report


def migrate(con, root):
    for name in ('006_personal_comparisons.sql', '007_comparison_result_bytes.sql'):
        path = root / 'crawler/sql' / name
        checksum = hashlib.sha256(path.read_bytes()).hexdigest()
        with con.cursor() as cur:
            cur.execute('SELECT checksum FROM research_schema_migration WHERE migration_id=%s', (path.name,))
            prior = cur.fetchone()
            if prior:
                if prior[0] != checksum:
                    raise ValueError('Personal comparison migration checksum changed')
                continue
            for sql in path.read_text(encoding='utf-8').split(';'):
                if sql.strip():
                    cur.execute(sql)
            cur.execute('INSERT INTO research_schema_migration(migration_id,checksum) VALUES(%s,%s)', (path.name, checksum))
        con.commit()


class MySQLComparisonArchive:
    def __init__(self, root, connect=None):
        self.root = root
        if connect is None:
            def connect():
                sys.path.insert(0, str(root / 'crawler'))
                from gradheat.vm_db import connect_vm
                return connect_vm(root / '.research/decision-workbench')
        self.connect = connect

    def save(self, result):
        report = render_report(result)
        cid = hashlib.sha256(canonical({'result': result, 'report_md': report}).encode('utf-8')).hexdigest()
        with self.connect() as con:
            try:
                with con.cursor() as cur:
                    cur.execute("SET time_zone = '+00:00'")
                    raw = canonical(result)
                    cur.execute('INSERT INTO personal_comparison(comparison_id,title,data_version,analysis_version,candidate_count,result_json,report_md,result_bytes) VALUES(%s,%s,%s,%s,%s,%s,%s,%s) ON DUPLICATE KEY UPDATE comparison_id=comparison_id',
                        (cid, result['input']['title'], result['data_version'], result['analysis_version'], len(result['cards']), raw, report, raw.encode('utf-8')))
                    reused = cur.rowcount == 0
                stored = self._get(con, cid)
                con.commit()
                return {'comparison_id': cid, 'reused': reused, 'created_at': stored['created_at'], 'title': stored['title']}
            except Exception:
                con.rollback()
                raise

    def _get(self, con, cid):
        with con.cursor() as cur:
            cur.execute('SELECT comparison_id,created_at,title,data_version,analysis_version,candidate_count,result_json,report_md,result_bytes FROM personal_comparison WHERE comparison_id=%s', (cid,))
            row = cur.fetchone()
        if row is None:
            raise KeyError(cid)
        value = dict(zip(('comparison_id', 'created_at', 'title', 'data_version', 'analysis_version', 'candidate_count', 'result', 'report_md'), row[:8]))
        value['created_at'] = value['created_at'].isoformat() + 'Z'
        # Binary originals preserve all digits; MySQL's queryable JSON is a derived view.
        value['result'] = json.loads(row[8] if row[8] is not None else value['result'])
        actual = hashlib.sha256(canonical({'result': value['result'], 'report_md': value['report_md']}).encode('utf-8')).hexdigest()
        if actual != cid:
            raise ValueError('保存的比较记录内容校验失败')
        return value

    def get(self, cid):
        with self.connect() as con:
            with con.cursor() as cur:cur.execute("SET time_zone = '+00:00'")
            value = self._get(con, cid)
            con.commit()
            return value

    def list(self):
        with self.connect() as con:
            with con.cursor() as cur:
                cur.execute("SET time_zone = '+00:00'")
                cur.execute('SELECT comparison_id,created_at,title,candidate_count FROM personal_comparison ORDER BY created_at DESC,comparison_id LIMIT 100')
                rows = cur.fetchall()
            con.commit()
        return [dict(comparison_id=r[0], created_at=r[1].isoformat() + 'Z', title=r[2], candidate_count=r[3]) for r in rows]
