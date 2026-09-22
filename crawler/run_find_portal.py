"""定位并校验各校研究生招生网站。

输出 data/school_portal.<ts>.jsonl —— 每校一行，含分层、域名、招生入口 URL、验证状态。

未验证通过的会明确标出（机制 9：不静默降级、不假装成功）。
"""

from __future__ import annotations

import glob
import json
import logging
import sys
from pathlib import Path

import yaml

from gradheat import portal, store

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s"
)
log = logging.getLogger("find_portal")

ROOT = Path(__file__).resolve().parent
REFS = ROOT / "refs"
DATA = ROOT / "data"


def load_refs() -> tuple[dict[str, str], dict[str, str], dict, set[str], set[str]]:
    domains = yaml.safe_load((REFS / "school_domains.yaml").read_text(encoding="utf-8"))[
        "domains"
    ]
    tiers = yaml.safe_load((REFS / "school_tiers.yaml").read_text(encoding="utf-8"))
    c985 = set(tiers["c985"])
    c211 = c985 | set(tiers["c211_extra"])
    return domains, tiers.get("aliases", {}) or {}, tiers, c985, c211


def main() -> int:
    domains, aliases, tiers, c985, c211 = load_refs()

    f = sorted(DATA.glob("yz_school_list.*.jsonl"))[-1]
    yz_rows = [json.loads(line) for line in f.open(encoding="utf-8")][1:]
    log.info("载入研招网清单 %d 所（%s）", len(yz_rows), f.name)

    targets = {r["name"]: domains[r["name"]] for r in yz_rows if r["name"] in domains}
    missing = [r["name"] for r in yz_rows if r["name"] not in domains]
    if missing:
        log.error("以下院校缺域名映射，跳过：%s", missing)

    log.info("开始探测 %d 所院校的研究生招生入口（并发 6，限速 0.3s）", len(targets))
    results = portal.probe_all(targets, workers=6, delay=0.3)

    by_name = {r["school"]: r for r in results}
    rows: list[dict] = []
    for r in yz_rows:
        name = r["name"]
        p = by_name.get(name)
        main = aliases.get(name, name)
        tier = "985" if main in c985 else ("211" if main in c211 else "syl")
        rows.append(
            {
                **r,
                "tier": tier,
                "legal_entity": main,
                "domain": domains.get(name),
                "portal_url": (p or {}).get("best", {}).get("url") if p else None,
                "portal_verified": bool((p or {}).get("verified")),
                "portal_candidates": (p or {}).get("candidates", []),
                "portal_score": (p or {}).get("best", {}).get("score") if p else None,
            }
        )

    ok = sum(1 for r in rows if r["portal_verified"])
    log.info("入口定位完成：%d/%d 通过验证", ok, len(rows))
    bad = [r["name"] for r in rows if not r["portal_verified"]]
    if bad:
        log.warning("未通过验证（%d 所）：%s", len(bad), bad)

    path = store.write_jsonl(
        "school_portal",
        rows,
        meta={
            "verified": ok,
            "unverified": len(rows) - ok,
            "probe_method": "DNS + HTTP + 校名/关键词内容校验",
        },
    )
    log.info("→ %s", path)
    return 0


if __name__ == "__main__":
    sys.exit(main())