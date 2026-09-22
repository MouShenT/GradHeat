"""校验参考名单自洽性 + 与已采集清单对齐。

机制：985/211 名单是手写的，必须用可验证的计数约束它（39 / 116），
      否则静默出错会污染整个分层结果。
"""

from __future__ import annotations

import glob
import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
REFS = ROOT / "refs"
DATA = ROOT / "data"

tiers = yaml.safe_load((REFS / "school_tiers.yaml").read_text(encoding="utf-8"))
domains = yaml.safe_load((REFS / "school_domains.yaml").read_text(encoding="utf-8"))["domains"]

c985 = tiers["c985"]
c211 = set(c985) | set(tiers["c211_extra"])
aliases: dict[str, str] = tiers.get("aliases", {}) or {}
exp = tiers["expected_counts"]

errors: list[str] = []


def resolve(name: str) -> str:
    """校区名归并到法人院校名。"""
    return aliases.get(name, name)


def tier_of(name: str) -> str:
    n = resolve(name)
    if n in c985:
        return "985"
    if n in c211:
        return "211"
    return "syl"


def check(label: str, got: int, want: int) -> None:
    ok = got == want
    print(f"{'✅' if ok else '❌'} {label}: {got} (期望 {want})")
    if not ok:
        errors.append(f"{label} 数量不符：{got} != {want}")


print("=== 名单自洽性 ===")
check("985", len(set(c985)), exp["985"])
check("211", len(c211), exp["211"])

# 985 必须是 211 的子集
not_in_211 = set(c985) - c211
if not_in_211:
    errors.append(f"985 不在 211 中：{not_in_211}")

# 域名字典覆盖
missing_domain = c211 - set(domains)
if missing_domain:
    print(f"⚠️  211 院校中缺域名映射：{sorted(missing_domain)}")

print("\n=== 与研招网采集清单对齐 ===")
f = sorted(DATA.glob("yz_school_list.*.jsonl"))[-1]
rows = [json.loads(line) for line in f.open(encoding="utf-8")][1:]
yz_names = {r["name"] for r in rows}
print(f"研招网清单: {len(yz_names)} 所")

tiered = {n: tier_of(n) for n in yz_names}
from collections import Counter as _C

print(f"  分层: {dict(_C(tiered.values()))}")
print(f"  仅双一流 : {len(yz_names - c211 - set(aliases))}")

not_collected = c211 - {resolve(n) for n in yz_names}
if not_collected:
    print(f"⚠️  211 中未出现在双一流清单（正常，部分 211 非双一流）：{sorted(not_collected)}")

missing_domain_yz = yz_names - set(domains)
if missing_domain_yz:
    errors.append(f"研招网清单中缺域名映射：{sorted(missing_domain_yz)}")

print()
if errors:
    print("❌ 校验未通过：")
    for e in errors:
        print("  -", e)
    sys.exit(1)
print("✅ 全部校验通过")