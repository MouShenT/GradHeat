from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'python_service'))
from gradheat_python import bootstrap
sys.path.insert(0, str(ROOT / 'tools/research'))
import collect_social_sources as social


class SocialCheckpointTests(unittest.TestCase):
    def test_existing_manifest_resumes_without_browser_or_health_changes(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            run_id = 'app-' + 'a' * 32
            batch = root / '.research/social/runs' / run_id
            batch.mkdir(parents=True)
            (batch / 'manifest.json').write_text('{}', encoding='utf-8')
            with patch.object(social, 'ROOT', root), patch.object(social, 'resume', return_value={'database_state': 'committed'}) as resume, patch.object(social, 'full_collection_active', side_effect=AssertionError('no new requests')):
                self.assertEqual(social.run(run_id_override=run_id)['database_state'], 'committed')
                resume.assert_called_once_with(batch)

    def test_incomplete_checkpoint_and_path_escape_never_refetch(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            run_id = 'app-' + 'a' * 32
            (root / '.research/social/runs' / run_id).mkdir(parents=True)
            with patch.object(social, 'ROOT', root), patch.object(social, 'full_collection_active', side_effect=AssertionError('no refetch')):
                with self.assertRaises(RuntimeError):
                    social.run(run_id_override=run_id)
                with self.assertRaises(ValueError):
                    social.run(run_id_override='../other')


if __name__ == '__main__':
    unittest.main()
