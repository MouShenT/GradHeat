"""列出已采集的院校清单（供人工核对/构建域名映射）。"""

from __future__ import annotations

import glob
import json
import sys
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"
f = sorted(DATA.glob("yz_school_list.*.jsonl"))[-1]
rows = [json.loads(line) for line in f.open(encoding="utf-8")][1:]

if "--names" in sys.argv:
    for i, r in enumerate(rows, 1):
        print(f"{i}\t{r['dwdm']}\t{r['name']}")
    sys.exit(0)

print(f"文件: {f.name}")
print(f"条数: {len(rows)}")
ids = [r["sch_id"] for r in rows]
names = [r["name"] for r in rows]
print(f"唯一 sch_id: {len(set(ids))}  唯一校名: {len(set(names))}")

import collections

dups = [n for n, c in collections.Counter(names).items() if c > 1]
print(f"重名校: {dups or '无'}")

dwdm_dup = [n for n, c in collections.Counter(r["dwdm"] for r in rows).items() if c > 1]
print(f"重单位代码: {dwdm_dup or '无'}")

print(f"\n主管部门分布: {collections.Counter(r['authority'] for r in rows).most_common()}")
print(f"自划线: {sum(1 for r in rows if r['is_self_line'])}")
print(f"研究生院: {sum(1 for r in rows if r['has_grad_school'])}")
print("\n地区分布:")
for area, c in collections.Counter(r["area"] for r in rows).most_common():
    print(f"  {area}: {c}")