import hashlib
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'crawler'))
from gradheat.publication_bytes import canonical_bytes, store_publication_bytes


class Cursor:
    def __init__(self, stored=None):
        self.stored = stored
    def execute(self, sql, parameters):
        if sql.startswith('INSERT IGNORE') and self.stored is None:
            self.stored = parameters[1]
    def fetchone(self):
        return (self.stored,)


class PublicationBytesTest(unittest.TestCase):
    def test_unicode_and_small_float_are_exact_python_bytes(self):
        value = {'院校': '合成样本', 'small': 1e-6, 'unknown': None, 'known_zero': 0}
        raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')
        version = hashlib.sha256(raw).hexdigest()
        self.assertEqual(canonical_bytes(version, value), raw)
        self.assertIn(b'1e-06', raw)
        self.assertEqual(store_publication_bytes(Cursor(), version, value), len(raw))
    def test_different_claimed_version_never_inserts(self):
        cur = Cursor()
        with self.assertRaises(ValueError):
            store_publication_bytes(cur, '0' * 64, {'synthetic': True})
        self.assertIsNone(cur.stored)
    def test_existing_corrupt_bytes_are_not_overwritten(self):
        value = {'synthetic': True}
        raw = b'{"synthetic":true}'
        version = hashlib.sha256(raw).hexdigest()
        cur = Cursor(b'{"synthetic":false}')
        with self.assertRaises(ValueError):
            store_publication_bytes(cur, version, value)
        self.assertEqual(cur.stored, b'{"synthetic":false}')
    def test_nan_cannot_create_a_publication(self):
        with self.assertRaises(ValueError):
            canonical_bytes('0' * 64, {'number': float('nan')})


if __name__ == '__main__':
    unittest.main()
