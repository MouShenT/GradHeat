import hashlib
import json
import time
import threading
from datetime import datetime, timezone

from gradheat.material_store import encode
from gradheat_workbench.heat import summarize


class HeatReader:
    def __init__(self, database):
        self.database = database
        self.lock = threading.RLock()
        self.cache = {}

    def read(self, unit):
        with self.lock:
            cached = self.cache.get(unit)
            if cached and time.monotonic() - cached[0] < 60:
                return cached[1]
            try:
                docs = []
                with self.database.connect() as con:
                    with con.cursor() as cur:
                        cur.execute("SELECT run_id FROM social_collection_run WHERE JSON_CONTAINS(JSON_EXTRACT(summary_json,'$.selected_units'),JSON_QUOTE(%s)) ORDER BY started_at DESC LIMIT 200", (unit,))
                        runs = [row[0] for row in cur.fetchall()]
                        rows = []
                        if runs:
                            cur.execute('SELECT snapshot_id,payload_json FROM social_content_snapshot WHERE run_id IN (' + ','.join(['%s'] * len(runs)) + ') ORDER BY observed_at DESC LIMIT 1000', tuple(runs))
                            rows = cur.fetchall()
                            for sid, raw in rows:
                                doc = json.loads(raw)
                                if (doc.get('id') != sid or doc.get('run_id') not in runs
                                        or hashlib.sha256(encode({k: v for k, v in doc.items() if k != 'id'}).encode()).hexdigest() != sid):
                                    raise ValueError('Social snapshot integrity failure')
                                docs.append(doc)
                    con.rollback()
                result = summarize(docs, unit, {}, datetime.now(timezone.utc).isoformat(), len(runs) == 200 or len(rows) == 1000)
                self.cache[unit] = (time.monotonic(), result)
                return result
            except Exception as error:
                if cached:
                    return dict(cached[1], read_state='using-last-verified-cache', refresh_error=type(error).__name__)
                return dict(unit=unit, platforms=[], read_state='unavailable', checked_at=None,
                    note='样本读取不可用，未知不记为热度零。')
