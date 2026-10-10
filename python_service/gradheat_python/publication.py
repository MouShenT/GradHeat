"""Production starts from committed MySQL publications, never D: research trees."""
import hashlib
import json
import threading
import time

from gradheat.material_store import encode


class PublicationUnavailable(RuntimeError):
    pass


def verified(version, text):
    if isinstance(text, bytes):
        text = text.decode('utf-8')
    payload = json.loads(text)
    if (hashlib.sha256(encode(payload).encode()).hexdigest() != version
            or not isinstance(payload.get('programmes'), list)
            or not isinstance(payload.get('history'), list)
            or not isinstance(payload.get('units'), list)):
        raise ValueError('Publication integrity failure')
    return payload


class PublicationReader:
    def __init__(self, database, settings):
        self.database = database
        self.settings = settings
        self.lock = threading.RLock()
        self.cached = None
        self.loaded_at = 0.0

    def get_version(self, version):
        """Queued work reads its immutable input even after the current head moves."""
        if self.settings.publication_file:
            payload = self.get(force=True)
            if hashlib.sha256(encode(payload).encode()).hexdigest() != version:
                raise ValueError('Explicit frozen publication differs from task input')
            return payload
        with self.database.connect() as con:
            with con.cursor() as cur:
                cur.execute('SELECT version_id,content FROM admissions_publication_bytes WHERE version_id=%s', (version,))
                row = cur.fetchone()
                if row is None:
                    raise LookupError('Task input publication is unavailable')
                payload = verified(*row)
            con.rollback()
        return payload
    def get(self, force=False):
        with self.lock:
            if self.cached and not force and time.monotonic() - self.loaded_at < self.settings.refresh_seconds:
                return self.cached
            try:
                if self.settings.publication_file:
                    if not self.settings.publication_sha:
                        raise ValueError('Frozen publication requires an explicit SHA')
                    payload = verified(self.settings.publication_sha, self.settings.publication_file.read_bytes())
                else:
                    with self.database.connect() as con:
                        with con.cursor() as cur:
                            # One join gives a coherent head and payload, unlike two unrelated reads.
                            cur.execute("SELECT p.version_id,p.content FROM admissions_head h JOIN admissions_publication_bytes p ON p.version_id=h.version_id WHERE h.name='current'")
                            row = cur.fetchone()
                            if row is None:
                                raise LookupError('No committed admissions publication')
                            payload = verified(*row)
                        con.rollback()
            except (ValueError, LookupError):
                raise
            except Exception as error:
                # No silently stale result is labelled as the latest committed publication.
                raise PublicationUnavailable(type(error).__name__) from error
            self.cached = payload
            self.loaded_at = time.monotonic()
            return payload


class FrozenPublication:
    def __init__(self, payload):
        self.payload = payload

    def get(self, force=False):
        return self.payload
