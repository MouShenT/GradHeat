import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'tools/research'))
import extract_admission_statistics as extraction


class AdmissionStatisticsExtractionTests(unittest.TestCase):
    def rows(self, *entries, flags=()):
        return [['考生编号', '专业', '初试总分', *flags],
                *[[identifier, '081200计算机科学与技术', score, *values]
                  for identifier, score, *values in entries]]

    def parse(self, rows):
        return extraction.parse_table(rows, {}, 'HTML table[0]')

    def test_qualification_does_not_override_negative_admission(self):
        rows=self.rows(('123456789012345','350','是','否'), flags=('是否通过','是否录取'))
        self.assertEqual(self.parse(rows), [])

    def test_negative_and_pending_admission_text_is_not_positive(self):
        for value in ('不予拟录取','未拟录取','取消拟录取','待定',''):
            with self.subTest(value=value):
                self.assertEqual(self.parse(self.rows(('123456789012345','350',value), flags=('录取结果',))), [])
        for value in ('是','拟录取','录取','拟录取（专项）'):
            with self.subTest(value=value):
                self.assertEqual(len(self.parse(self.rows(('123456789012345','350',value), flags=('录取结果',)))), 1)

    def test_colliding_masks_keep_both_rows_even_with_equal_scores(self):
        for score in ('350','360'):
            records=self.parse(self.rows(('123456******001','350'),('123456******001',score)))
            self.assertEqual(len(extraction.deduplicate_records(records)), 2)

    def test_duplicate_complete_identifier_requires_consistent_values(self):
        records=self.parse(self.rows(('123456789012345','350'),('123456789012345','350')))
        self.assertEqual(len(extraction.deduplicate_records(records)), 1)
        records=self.parse(self.rows(('123456789012345','350'),('123456789012345','360')))
        with self.assertRaisesRegex(ValueError, 'original-page review'):
            extraction.deduplicate_records(records)

    def test_conflicting_pools_cannot_silently_select_last_row(self):
        records=self.parse(self.rows(('123456789012345','350'),('123456789012345','350')))
        records[1]['pool']='专业：085404计算机技术'
        with self.assertRaises(ValueError):
            extraction.deduplicate_records(records)

    def test_export_labels_masked_counts_and_excludes_identifiers(self):
        rows=self.rows(('123456******001','350'),('123456******001','360'))
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);raw=root/'roster.html';raw.write_text('<table></table>', encoding='utf-8')
            unit=dict(name='样本大学',group='985')
            doc=dict(year=2026,source_tier='primary',retained=True,title='计算机硕士拟录取名单',
                     raw_path=str(raw),url='https://school.example.edu/roster.html')
            with patch.object(extraction.d,'ROOT',root), patch.object(extraction.d,'WORK',root), \
                 patch.object(extraction.d,'read',return_value={'units':[unit]}), \
                 patch.object(extraction.d.priority,'load',return_value=[unit]), \
                 patch.object(extraction.d,'docs_for',return_value=[doc]), \
                 patch.object(extraction.d,'textfile',return_value='计算机硕士拟录取名单'), \
                 patch.object(extraction.evidence,'rawhtml',return_value='<table></table>'), \
                 patch.object(extraction.evidence,'grid',return_value=rows), \
                 patch.object(extraction.d,'dump') as dumped:
                extraction.run()
            output=dumped.call_args.args[1]
            self.assertEqual(len(output),1)
            result=output[0]
            self.assertEqual((result['n'],result['minimum'],result['maximum']), (2,350,360))
            self.assertEqual(result['count_definition'],'observed-rows')
            self.assertEqual(result['masked_identifier_rows'],2)
            self.assertNotIn('identifier_hash', json.dumps(output))
            self.assertNotIn('123456', json.dumps(output))


if __name__ == '__main__':
    unittest.main()
