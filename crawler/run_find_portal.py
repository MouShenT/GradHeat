"""定位并校验各校研究生招生网站。

输出 data/school_portal.<ts>.jsonl —— 每校一行，含分层、域名、招生入口 URL、验证状态，
以及完整探测证据（portal_dns / portal_tried / probed_at / run_id）。

未验证通过的会明确标出（机制 9：不静默降级、不假装成功）；
单校探测失败不中断整批，失败校带 portal_probe_error 落盘。
"""

from __future__ import annotations

import glob
import json
import logging
import sys
import uuid
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


def build_rows(
    yz_rows: list[dict],
    results: list[dict],
    domains: dict[str, str],
    aliases: dict[str, str],
    c985: set[str],
    c211: set[str],
    run_id: str,
) -> list[dict]:
    """yz 清单行并入探测结果。p 缺失或 best=None 都不崩溃，失败项照常落盘。"""
    by_name = {r["school"]: r for r in results}
    rows: list[dict] = []
    for r in yz_rows:
        name = r["name"]
        p = by_name.get(name) or {}
        best = p.get("best") or {}
        main = aliases.get(name, name)
        tier = "985" if main in c985 else ("211" if main in c211 else "syl")
        rows.append(
            {
                **r,
                "tier": tier,
                "legal_entity": main,
                "domain": domains.get(name),
                "portal_url": best.get("url"),
                "portal_verified": bool(p.get("verified")),
                "portal_candidates": p.get("candidates") or [],
                "portal_dns": p.get("dns") or {},
                "portal_tried": p.get("tried") or [],
                "portal_score": best.get("score"),
                "portal_probe_error": p.get("error"),
                "probed_at": p.get("probed_at"),
                "run_id": run_id,
            }
        )
    return rows


def main() -> int:
    domains, aliases, tiers, c985, c211 = load_refs()

    f = sorted(DATA.glob("yz_school_list.*.jsonl"))[-1]
    yz_rows = [json.loads(line) for line in f.open(encoding="utf-8")][1:]
    log.info("载入研招网清单 %d 所（%s）", len(yz_rows), f.name)

    targets = {r["name"]: domains[r["name"]] for r in yz_rows if r["name"] in domains}
    missing = [r["name"] for r in yz_rows if r["name"] not in domains]
    if missing:
        log.error("以下院校缺域名映射，跳过探测：%s", missing)

    log.info(
        "开始探测 %d 所院校的研究生招生入口（并发 6，限速 0.3s；硬条件：身份/用途/落地域）",
        len(targets),
    )
    run_id = uuid.uuid4().hex[:12]
    results = portal.probe_all(targets, workers=6, delay=0.3)

    rows = build_rows(yz_rows, results, domains, aliases, c985, c211, run_id)

    ok = sum(1 for r in rows if r["portal_verified"])
    log.info("入口定位完成：%d/%d 通过验证", ok, len(rows))
    bad = [r["name"] for r in rows if not r["portal_verified"]]
    if bad:
        log.warning("未通过验证（%d 所）：%s", len(bad), bad)

    path = store.write_jsonl(
        "school_portal",
        rows,
        meta={
            "run_id": run_id,
            "verified": ok,
            "unverified": len(rows) - ok,
            "probe_method": "DNS(限时并发) + HTTP(单次快速失败) + 身份/用途/落地域硬条件，分数仅排序",
            "probe_params": {
                "workers": 6,
                "delay": 0.3,
                "timeout": portal.PROBE_TIMEOUT,
                "retries": portal.PROBE_RETRIES,
                "dns_timeout": portal.DNS_TIMEOUT,
            },
        },
    )
    log.info("→ %s", path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
