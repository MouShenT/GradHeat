import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools/research'))
import build_unit_dossiers as d


class AttachmentAvailabilityTests(unittest.TestCase):
    def test_captcha_download_page_cannot_replace_the_saved_original(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);raw=root/'old.pdf';raw.write_bytes(b'%PDF-test-preserved')
            text=root/'old.txt';text.write_text('软件工程 初试成绩 拟录取',encoding='utf-8')
            page=root/'new.html';page.write_text('<body>请输入验证码下载附件</body>',encoding='utf-8')
            response=root/'new.txt';response.write_text('请输入验证码下载附件',encoding='utf-8')
            url='https://example.edu.cn/system/_content/download.jsp?wbfileid=one'
            unit=dict(name='样本大学',documents=[dict(url=url,title='2025拟录取名单.pdf',year=2025,
                collection_file=dict(artifact=str(raw),text_artifact=str(text)))])
            current=dict(unit=unit['name'],url=url,title='2025拟录取名单.pdf',year=2025,status='html-saved',
                raw_path=str(page),text_path=str(response),retrieved_at='new')
            with patch.object(d,'read',side_effect=lambda path,default=None:[current] if Path(path).name=='live-sources.json' else []):
                actual=d.docs_for(unit)
            self.assertEqual(actual[0]['raw_path'],str(raw))
            self.assertTrue(actual[0]['retained'])
            self.assertEqual(actual[0]['latest_access']['status'],'verification-page')
            self.assertEqual(raw.read_bytes(),b'%PDF-test-preserved')

    def test_an_admissions_article_mentioning_captcha_is_still_readable(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);page=root/'article.html';page.write_text('<body>Admissions</body>',encoding='utf-8')
            text=root/'article.txt';text.write_text('报名说明：请输入验证码后完成网报。'+'招生专业说明。'*40,encoding='utf-8')
            result=d.classify_retained_source(dict(url='https://example.edu.cn/news/one',title='2027硕士招生简章',
                raw_path=str(page),text_path=str(text),status='html-saved',retained=True))
            self.assertTrue(result['retained'])
            self.assertEqual(result['status'],'html-saved')


if __name__=='__main__':unittest.main()
