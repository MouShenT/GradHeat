"""探针：dump 研招网院校详情页的可提取字段。"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lxml import html as lxml_html  # noqa: E402

from gradheat.net import Session  # noqa: E402

URL = sys.argv[1] if len(sys.argv) > 1 else "https://yz.chsi.com.cn/sch/schoolInfo--schId-367878.dhtml"

sess = Session(proxy=None)
resp = sess.get(URL)
print("HTTP", resp.status_code, len(resp.text))
doc = lxml_html.fromstring(resp.text)

print("\n=== title ===")
t = doc.cssselect("title")
print(t[0].text_content().strip() if t else "(none)")

print("\n=== 所有含「院校」/「招生」的块 class ===")
for el in doc.iter():
    cls = el.get("class") or ""
    if any(k in cls for k in ("sch-", "yx-", "info", "detail", "contact")):
        txt = re.sub(r"\s+", " ", el.text_content()).strip()
        if 3 < len(txt) < 200:
            print(f"[{cls}] {txt}")

print("\n=== 外链（可能是研究生院官网）===")
seen = set()
for a in doc.cssselect("a"):
    h = a.get("href") or ""
    if h.startswith("http") and "chsi" not in h and h not in seen:
        seen.add(h)
        print(f"  {a.text_content().strip()[:24]:26} {h}")

print("\n=== 正文文本片段 ===")
body = re.sub(r"\s+", " ", doc.text_content())
for kw in ["研究生院", "官网", "地址", "电话", "邮编", "招生"]:
    for m in list(re.finditer(kw, body))[:2]:
        print(f"  {kw}: ...{body[max(0, m.start()-50):m.start()+80]}...")