"""把采集结果装入 MySQL（经 SSH 隧道 → VM 上的 gradheat-mysql）。

覆盖：
  - 建表（sql/*.sql）
  - province / school_alias 参考表
  - school 主表（148 所）—— 合并 refs 里的分层、法人归并、域名、招生入口
  - school_portal_probe 探测证据（若已有 data/school_portal.*.jsonl）
  - fetch_log 采集批次留痕

缺失即 NULL：未探测到的入口写 NULL，不写空串、不写 0。

用法：
  ssh -N -L 13306:127.0.0.1:3306 ms@192.168.43.150 &   # 先建隧道
  python run_load_db.py
"""

from __future__ import annotations

import glob
import json
import logging
import sys
from pathlib import Path
from urllib.parse import urlparse

import yaml

from gradheat import db

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s"
)
log = logging.getLogger("load_db")

ROOT = Path(__file__).resolve().parent
REFS = ROOT / "refs"
DATA = ROOT / "data"


def _latest(pattern: str) -> Path | None:
    files = sorted(DATA.glob(pattern))
    return files[-1] if files else None


def load_refs() -> tuple[dict, dict, set, set]:
    tiers = yaml.safe_load((REFS / "school_tiers.yaml").read_text(encoding="utf-8"))
    domains = yaml.safe_load((REFS / "school_domains.yaml").read_text(encoding="utf-8"))["domains"]
    provinces = yaml.safe_load((REFS / "provinces.yaml").read_text(encoding="utf-8"))["provinces"]
    c985 = set(tiers["c985"])
    c211 = c985 | set(tiers["c211_extra"])
    return domains, provinces, c985, c211


def build_school_rows() -> tuple[list[dict], dict]:
    domains, provinces, c985, c211 = load_refs()
    tiers = yaml.safe_load((REFS / "school_tiers.yaml").read_text(encoding="utf-8"))
    aliases: dict[str, str] = tiers.get("aliases", {}) or {}

    f = _latest("yz_school_list.*.jsonl")
    if not f:
        raise SystemExit("找不到 data/yz_school_list.*.jsonl —— 先跑 run_school_list.py")
    with f.open(encoding="utf-8") as fh:
        meta = json.loads(fh.readline())["_meta"]
        yz_rows = [json.loads(line) for line in fh]

    # 招生入口（若已探测）
    portals: dict[str, dict] = {}
    pf = _latest("school_portal.*.jsonl")
    if pf:
        with pf.open(encoding="utf-8") as fh:
            next(fh)
            for line in fh:
                r = json.loads(line)
                portals[r["name"]] = r
        log.info("并入招生入口探测结果：%s（%d 条）", pf.name, len(portals))
    else:
        log.warning("尚无 school_portal.*.jsonl —— portal_url 全部留 NULL（未探测 ≠ 不存在）")

    fetched_at = meta["fetched_at"]
    rows: list[dict] = []
    for r in yz_rows:
        name = r["name"]
        legal = aliases.get(name, name)
        tier = "985" if legal in c985 else ("211" if legal in c211 else "syl")
        p = portals.get(name) or {}
        rows.append(
            {
                "dwdm": r["dwdm"],
                "sch_id": db.clean_text(r.get("sch_id")),
                "name": name,
                "legal_entity": legal,
                "tier": tier,
                "province_code": db.clean_text(r.get("ssdm")),
                "area": db.clean_text(r.get("area")),
                "authority": db.clean_text(r.get("authority")),
                "is_syl": int(bool(r.get("is_syl"))),
                # 研招网不再返回 985/211 标签，按本项目历史名单判定
                "is_985": int(tier == "985"),
                "is_211": int(tier in ("985", "211")),
                "is_self_line": int(bool(r.get("is_self_line"))),
                "has_grad_school": int(bool(r.get("has_grad_school"))),
                "domain": db.clean_text(domains.get(name)),
                "portal_url": db.clean_text(p.get("portal_url")),
                "portal_score": p.get("portal_score"),
                "portal_verified": int(bool(p.get("portal_verified"))),
                "source_level": r.get("source_level", "L1"),
                "source_url": r.get("source_url"),
                "fetched_at": fetched_at.replace("T", " ")[:19],
            }
        )

    for code, info in provinces.items():
        if code not in {r["province_code"] for r in rows}:
            log.warning("provinces.yaml 里的 %s(%s) 无院校使用", code, info["name"])

    return rows, {"meta": meta, "aliases": aliases, "provinces": provinces, "portal_file": pf}


def build_probe_rows(conn, ref: dict) -> list[dict]:
    pf = ref["portal_file"]
    if not pf:
        return []
    ids = db.school_id_map(conn)
    with pf.open(encoding="utf-8") as fh:
        next(fh)
        portal_rows = [json.loads(line) for line in fh]

    fetched_at = ref["meta"]["fetched_at"].replace("T", " ")[:19]
    out: list[dict] = []
    for r in portal_rows:
        sid = ids.get(r["dwdm"])
        if not sid:
            continue
        best_url = r.get("portal_url")
        tried = r.get("portal_candidates_tried") or r.get("tried") or []

        out += [
            {
                "school_id": sid,
                "fetched_at": fetched_at,
                "url": t["url"],
                "dns_ok": 1,
                "http_status": t.get("status"),
                "score": t.get("score"),
                "is_best": int(t["url"] == best_url),
                "error": t.get("err"),
            }
            for t in tried
            if t.get("url")
        ]

        # DNS 通过但没走进 HTTP 的候选（同 host 已成功过一次就 break 了），
        # 也是探测证据 —— 不记下来就看不出「探过哪些、为什么没选它」。
        attempted_hosts = {urlparse(t["url"]).hostname for t in tried if t.get("url")}
        out += [
            {
                "school_id": sid,
                "fetched_at": fetched_at,
                "url": f"https://{host}/",
                "dns_ok": 1,
                "http_status": None,
                "score": None,
                "is_best": 0,
                "error": "DNS 通过，未发起 HTTP（同域名已有候选成功）",
            }
            for host in (r.get("portal_candidates") or [])
            if host not in attempted_hosts
        ]
    return out


def main() -> int:
    with db.connect() as conn:
        done = db.apply_schema(conn)
        log.info("建表完成：%s", done)

        rows, ref = build_school_rows()

        n_prov = db.upsert_provinces(
            conn,
            [
                {"code": c, "name": i["name"], "region": i.get("region")}
                for c, i in ref["provinces"].items()
            ],
        )
        log.info("province 写入 %d 行", n_prov)

        n_alias = db.upsert_aliases(conn, ref["aliases"])
        log.info("school_alias 写入 %d 行", n_alias)

        n_school = db.upsert_schools(conn, rows)
        log.info("school 写入 %d 行", n_school)

        probes = build_probe_rows(conn, ref)
        n_probe = db.upsert_probes(conn, probes)
        log.info("school_portal_probe 写入 %d 行", n_probe)

        run_id = db.new_run_id()
        db.log_fetch(
            conn,
            run_id=run_id,
            dataset="yz_school_list",
            target="双一流院校库 ylgx=1",
            started_at=ref["meta"]["fetched_at"].replace("T", " ")[:19],
            rows_fetched=ref["meta"]["fetched_count"],
            expected_rows=len(rows),
            content_hash=ref["meta"]["content_hash"],
            baseline_note=None,
            outcome="ok",
            note=(
                f"研招网按招生单位分列得 {len(rows)} 行；双一流按院校计数为 147。"
                "差额为 中国矿业大学(北京)/中国石油大学(北京)/中国地质大学(北京)/华北电力大学(保定) "
                "四个独立招生单位 —— 口径差异，非重复。985/211 标签研招网已停用，按本项目历史名单判定。"
            ),
        )
        log.info("fetch_log 已写入 run_id=%s", run_id)

        # 自检：读回计数
        with conn.cursor() as cur:
            for tbl in ("school", "school_alias", "province", "school_portal_probe", "fetch_log"):
                cur.execute(f"SELECT COUNT(*) FROM {tbl}")
                log.info("  %-22s %d 行", tbl, cur.fetchone()[0])
            cur.execute(
                "SELECT tier, COUNT(*) FROM school GROUP BY tier ORDER BY COUNT(*) DESC"
            )
            log.info("  分层：%s", dict(cur.fetchall()))
            cur.execute(
                "SELECT COUNT(*) FROM school WHERE portal_verified=1"
            )
            log.info("  入口已验证：%s / %s", cur.fetchone()[0], len(rows))
            cur.execute(
                "SELECT COUNT(*) FROM school WHERE area IS NULL OR province_code IS NULL"
            )
            missing = cur.fetchone()[0]
            if missing:
                log.warning("  有 %d 所的 area/province 为 NULL，需回查", missing)
    return 0


if __name__ == "__main__":
    sys.exit(main())