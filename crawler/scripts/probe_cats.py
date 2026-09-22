"""探针：遍历研招网院校详情页的所有 categoryId 标签，看各页有什么数据。"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lxml import html as lxml_html  # noqa: E402

from gradheat.net import Session  # noqa: E402

SID = sys.argv[1] if len(sys.argv) > 1 else "367878"
CATS = [
    481342, 481347, 481359, 481367, 481370,
    481373, 481376, 481381, 481384, 665611,
]
BASE = "https://yz.chsi.com.cn"

sess = Session(proxy=None)
for cid in CATS:
    url = f"{BASE}/sch/schoolInfo--schId-{SID},categoryId-{cid}.dhtml"
    try:
        resp = sess.get(url, referer=f"{BASE}/sch/schoolInfo--schId-{SID}.dhtml")
    except Exception as exc:  # noqa: BLE001
        print(f"[{cid}] 失败 {exc}")
        continue
    doc = lxml_html.fromstring(resp.text)
    title = doc.cssselect("title")
    title = title[0].text_content().strip() if title else "?"
    h1 = doc.cssselect("h1, .sch-column-title, .content-title")
    h1 = [re.sub(r"\s+", " ", e.text_content()).strip() for e in h1[:4]]
    body = re.sub(r"\s+", " ", doc.text_content())
    # 去掉脚本/样式的残留
    body = re.sub(r"[.#][\w-]+\s*\{[^}]*\}", " ", body)
    body = re.sub(r"\s+", " ", body).strip()
    print(f"\n===== categoryId={cid} | {title} | {h1}")
    print(f"     长度={len(body)}")
    print(f"     片段: {body[:300]}")