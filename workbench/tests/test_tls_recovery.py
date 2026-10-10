import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools/research'))
import recover_gap_tls as recovery


class TLSRecoveryTests(unittest.TestCase):
    def test_localized_windows_error_remains_a_failed_observation(self):
        task = dict(unit='测试大学', url='https://example.edu.cn/catalogue', unit_info={})
        process = subprocess.CompletedProcess([], 35, b'000\nhttps://example.edu.cn/catalogue\n\n0',
                                              '证书验证失败'.encode('gb18030'))
        with tempfile.TemporaryDirectory() as temp, patch.object(recovery, 'BATCH', Path(temp)), \
                patch.object(recovery.subprocess, 'run', return_value=process) as command:
            result = recovery.verified_curl(task)
            self.assertEqual(result['status'], 'fetch-failed')
            self.assertTrue(result['error'])
            self.assertNotIn('raw_path', result)
            self.assertNotIn('text', command.call_args.kwargs)

    def test_timeout_is_recorded_without_stopping_other_sources(self):
        task = dict(unit='测试大学', url='https://example.edu.cn/catalogue', unit_info={})
        with tempfile.TemporaryDirectory() as temp, patch.object(recovery, 'BATCH', Path(temp)), \
                patch.object(recovery.subprocess, 'run', side_effect=subprocess.TimeoutExpired('curl', 30)):
            result = recovery.verified_curl(task)
            self.assertEqual(result['error'], 'TimeoutExpired')
            self.assertEqual(result['status'], 'fetch-failed')

    def test_verified_success_preserves_original_bytes(self):
        task = dict(unit='测试大学', url='https://example.edu.cn/catalogue', unit_info={})
        original = b'<html><title>Admissions</title><body>2027 catalogue</body></html>'
        def command(arguments, **kwargs):
            Path(arguments[arguments.index('--output') + 1]).write_bytes(original)
            return subprocess.CompletedProcess(arguments, 0,
                b'200\nhttps://example.edu.cn/catalogue\ntext/html\n0', b'')
        with tempfile.TemporaryDirectory() as temp, patch.object(recovery, 'BATCH', Path(temp)), \
                patch.object(recovery.subprocess, 'run', side_effect=command), \
                patch.object(recovery.r, 'allowed', return_value=True):
            result = recovery.verified_curl(task)
            self.assertEqual(result['status'], 'html-saved')
            self.assertEqual(Path(result['raw_path']).read_bytes(), original)
            self.assertEqual(result['tls_verify_result'], 0)


if __name__ == '__main__':
    unittest.main()
