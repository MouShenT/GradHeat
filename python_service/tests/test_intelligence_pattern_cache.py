"""Synthetic equivalence and cache-boundary checks; no database or network IO."""
from pathlib import Path
import re
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from gradheat_core import intelligence as core


def uncached_pattern(token):
    pattern = re.escape(core.unit_key(token)).replace(r'\ ', r'\s*')
    if token.isascii():
        pattern = r'(?<![A-Za-z])' + pattern + r'(?![A-Za-z])'
    return re.compile(pattern, re.I)


class IntelligencePatternCacheTests(unittest.TestCase):
    def setUp(self):
        core._mention_pattern.cache_clear()

    def tearDown(self):
        core._mention_pattern.cache_clear()

    def test_cached_matching_preserves_unicode_whitespace_escaping_and_ascii_boundaries(self):
        tokens = ['BUPT', '中国地质大学（北京）', '国科大 数学科学学院',
                  '合成A+B(学院)', 'ＢＵＰＴ', ' 科大 ', '']
        samples = ['BUPT bupt XBUPTX 1BUPT2 BUPT中文',
                   '中国地质大学(北京)考研', '国科大\n 数学科学学院复试',
                   '合成A+B(学院) 不是合成AAAB学院', 'XＢＵＰＴX 科大 考研', '']
        for token in tokens:
            for text in samples:
                with self.subTest(token=token, text=text):
                    value = core.unicodedata.normalize('NFKC', text)
                    expected = [m.span() for m in uncached_pattern(token).finditer(value)]
                    self.assertEqual([m.span() for m in core._mention_pattern(token).finditer(value)], expected)

    def test_school_attribution_and_claim_bytes_match_without_caching_patterns(self):
        units = ['电子科技大学', '西安电子科技大学', '北京邮电大学', '南京邮电大学',
                 '数学科学学院', '中国地质大学（北京）', '中国地质大学(北京)']
        docs = [
            dict(id='a', title='西安电子科技大学与成电考研', text='2026 西电复试线330。2026 成电普通统考名额80。'),
            dict(id='b', title='<b>北邮</b>与NJUPT考研', text='2026 北邮复试线350。2026 南邮录取最低分999。'),
            dict(id='c', title='国科大数学科学学院研究生复试', text='2026 复试线320。'),
            dict(id='d', title='中国地质大学(北京)考研', text='2026 本科跨考报考接受。'),
            dict(id='e', title='未提院校的计算机考研经验', query='BUPT 408'),
            dict(id='f', title='数学科学学院高考校园参观', query='考研'),
            dict(id='g', title='未提院校的计算机考研经验', query='北邮 南邮 408'),
        ]

        def result():
            rows = []
            for doc in docs:
                links = core.identify(doc, units)
                rows.append((links, core.plausible_claims(doc, links)))
            return core.canonical(rows).encode('utf-8')

        with patch.object(core, '_mention_pattern', uncached_pattern):
            expected = result()
        self.assertEqual(result(), expected)
        self.assertEqual(result(), expected)

    def test_warm_registry_survives_shared_regex_cache_eviction(self):
        units = [f'合成大学{n:04d}' for n in range(600)]
        doc = dict(title='合成大学0000与合成大学0599计算机考研')
        expected = core.identify(doc, units)
        re.purge()
        # A second full registry pass must reuse compiled patterns even after
        # unrelated regex users evict Python's much smaller shared cache.
        with patch.object(core.re, 'compile', wraps=re.compile) as compile_pattern:
            self.assertEqual(core.identify(doc, units), expected)
        self.assertEqual(compile_pattern.call_count, 0)
        self.assertEqual(core._mention_pattern.cache_info().hits, len(units))
        expected[0]['weight'] = 999
        self.assertEqual(sum(row['weight'] for row in core.identify(doc, units)), 1)

    def test_alias_changes_do_not_reuse_an_old_name_catalogue(self):
        name = '合成测试大学'
        with patch.dict(core.ALIASES, {name: ['旧别名']}):
            self.assertTrue(core.identify(dict(title='旧别名考研'), [name]))
            core.ALIASES[name] = ['新别名']
            self.assertTrue(core.identify(dict(title='新别名考研'), [name]))
            self.assertEqual(core.identify(dict(title='旧别名考研'), [name]), [])

    def test_cache_is_bounded_and_eviction_preserves_matching(self):
        maximum = core._mention_pattern.cache_info().maxsize
        self.assertIsNotNone(maximum)
        for n in range(maximum + 1):
            core._mention_pattern(f'合成院校{n:05d}')
        self.assertEqual(core._mention_pattern.cache_info().currsize, maximum)
        token = '合成院校00000'
        self.assertEqual(core._mention_pattern(token).pattern, uncached_pattern(token).pattern)
        self.assertEqual(core._mention_pattern.cache_info().currsize, maximum)


if __name__ == '__main__':
    unittest.main()
