import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'tools/research'))
import fetch_github_sources as fetcher


class PublicGitFallbackTests(unittest.TestCase):
    def test_failed_api_uses_observed_anonymous_head_and_keeps_metadata_unknown(self):
        repo='Laz8Noy/kaoyan408-share';commit='a'*40
        stream=io.BytesIO()
        with zipfile.ZipFile(stream,'w') as z:z.writestr('repo-root/data/value.json','{"plan":12}')
        zipped=stream.getvalue();calls=[]
        class Download:
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def raise_for_status(self):pass
            def iter_content(self,*args):yield zipped
        def get(url,**kwargs):
            calls.append(url)
            if url.startswith('https://api.github.com/'):
                response=fetcher.requests.Response();response.status_code=403
                raise fetcher.requests.HTTPError(response=response)
            return Download()
        remote=subprocess.CompletedProcess([],0,'ref: refs/heads/main\tHEAD\n'+commit+'\tHEAD\n','')
        with tempfile.TemporaryDirectory() as temp,patch.object(fetcher,'OUT',Path(temp)), \
                patch.object(fetcher.requests,'get',side_effect=get),patch.object(fetcher.subprocess,'run',return_value=remote) as git:
            report=fetcher.fetch(repo)
            self.assertEqual(report['commit'],commit)
            self.assertIsNone(report['license'])
            self.assertEqual(report['discovery_transport'],'anonymous-git-ls-remote')
            self.assertEqual(report['sha256'],hashlib.sha256(zipped).hexdigest())
            self.assertTrue((Path(report['path'])/'data/value.json').is_file())
            evidence=json.loads((Path(temp)/'raw'/('Laz8Noy--kaoyan408-share-'+commit+'-git-ref.json')).read_text())
            self.assertEqual(evidence['api_failure']['http_status'],403)
            self.assertIn('credential.helper=',git.call_args.args[0])
            self.assertEqual(git.call_args.kwargs['env']['GIT_TERMINAL_PROMPT'],'0')
        self.assertEqual(calls,['https://api.github.com/repos/'+repo,'https://codeload.github.com/'+repo+'/zip/'+commit])

    def test_ambiguous_head_is_not_downloaded(self):
        remote=subprocess.CompletedProcess([],0,'ref: refs/heads/main\tHEAD\n'+'a'*40+'\tHEAD\n'+'b'*40+'\tHEAD\n','')
        with patch.object(fetcher.subprocess,'run',return_value=remote),patch.object(fetcher.requests,'get') as request:
            with self.assertRaises(ValueError):fetcher.fetch_from_public_git('Laz8Noy/kaoyan408-share')
            request.assert_not_called()


if __name__=='__main__':unittest.main()
