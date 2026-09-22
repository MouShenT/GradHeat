"""探针：找出研招网院校详情页各标签页的 URL 规律。"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from gradheat.net import Session  # noqa: E402

SID = sys.argv[1] if len(sys.argv) > 1 else "367878"
URL = f"https://yz.chsi.com.cn/sch/schoolInfo--schId-{SID}.dhtml"

sess = Session(proxy=None)
resp = sess.get(URL)
h = resp.text

print("=== 页内所有 /sch/ 链接 ===")
for m in sorted(set(re.findall(r"/sch/[A-Za-z0-9_\-.,]+\.dhtml", h))):
    print(" ", m)

print("\n=== 标签名与对应 href（从 JS 数据里找）===")
for m in re.finditer(r"\{[^{}]*?(?:title|name)\s*:\s*['\"]([^'\"]{2,12})['\"][^{}]*?(?:url|href)\s*:\s*['\"]([^'\"]+)['\"]", h):
    print(f"  {m.group(1):12} {m.group(2)}")

print("\n=== 含 schId 的链接（含参数形式）===")
for m in sorted(set(re.findall(r"[A-Za-z0-9_\-]+--[^\"'<> ]{0,120}schId-?\d+[^\"'<> ]{0,120}", h)))[:30]:
    print(" ", m)