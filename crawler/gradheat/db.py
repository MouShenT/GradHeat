"""写入 MySQL（经 SSH 隧道到 VM 上的 gradheat-mysql）。

连接默认 127.0.0.1:13306 —— 即 README 里那条隧道映射，不是容器端口直连。
凭据从 crawler/.env 读；缺失时给出可执行的修复提示，而不是抛一个 `Access denied` 让人猜。

设计约束：
  - 缺失字段写 NULL，绝不写 0（0 是「已知为零」，NULL 是「未知」）。
  - 事实表用 row_key 幂等：同一事实重复采集只更新数值，不产生新行。
  - 每次采集无论成功失败都写 fetch_log —— 空结果必须留痕（机制 9 ①）。
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator, Sequence

import pymysql

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
SQL_DIR = ROOT / "sql"
ENV_FILE = ROOT / ".env"

# 原始 HTML 里混入的图标字体字形（Private Use Area），如研招网 location 图标 。
_PUA = re.compile("[-]")


def _load_env() -> dict[str, str]:
    env = dict(os.environ)
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            env.setdefault(k.strip(), v.strip())
    return env


@contextmanager
def connect(*, host: str | None = None) -> Iterator[pymysql.connections.Connection]:
    env = _load_env()
    cfg = {
        "host": host or env.get("GRADHEAT_DB_HOST", "127.0.0.1"),
        "port": int(env.get("GRADHEAT_DB_PORT", "13306")),
        "user": env.get("GRADHEAT_DB_USER", "gradheat"),
        "password": env.get("GRADHEAT_DB_PASSWORD", ""),
        "database": env.get("GRADHEAT_DB_NAME", "gradheat"),
        "charset": "utf8mb4",
        "autocommit": False,
    }
    if not cfg["password"]:
        raise RuntimeError(
            f"缺少数据库密码。请在 {ENV_FILE} 写入 GRADHEAT_DB_PASSWORD=...\n"
            "取法见 VM 上 /opt/gradheat/infra/docker/.env 的 MYSQL_PASSWORD。"
        )
    conn = pymysql.connect(**cfg)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def apply_schema(conn: pymysql.connections.Connection) -> list[str]:
    """按文件名顺序执行 sql/*.sql。返回执行的文件名列表。"""
    done: list[str] = []
    for path in sorted(SQL_DIR.glob("*.sql")):
        sql = path.read_text(encoding="utf-8")
        with conn.cursor() as cur:
            for stmt in _split_statements(sql):
                cur.execute(stmt)
        done.append(path.name)
    return done


def _split_statements(sql: str) -> list[str]:
    """按分号切分，但跳过注释行 —— 注释里也可能出现分号。"""
    out: list[str] = []
    buf: list[str] = []
    for line in sql.splitlines():
        stripped = line.strip()
        if stripped.startswith("--") or not stripped:
            continue
        buf.append(line)
        if stripped.endswith(";"):
            stmt = "\n".join(buf).strip().rstrip(";").strip()
            if stmt:
                out.append(stmt)
            buf = []
    if (tail := "\n".join(buf).strip()):
        out.append(tail)
    return out


def clean_text(v: Any) -> str | None:
    """剥离 PUA 图标字形并归一空白。空串一律转 None —— 缺失就留 NULL。"""
    if v is None:
        return None
    s = _PUA.sub("", str(v))
    s = re.sub(r"\s+", " ", s).strip()
    return s or None


def row_key(*parts: Any) -> str:
    """自然键的规范化哈希。None 与空串都归一为 \\x00，避免 None 在 SQL 里互不相等。"""
    norm = "\x1f".join("\x00" if p is None or p == "" else str(p) for p in parts)
    return hashlib.md5(norm.encode("utf-8")).hexdigest()[:16]


def now_utc() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def new_run_id() -> str:
    return str(uuid.uuid4())


# ============================================================
# 载入：院校
# ============================================================


def upsert_provinces(conn: pymysql.connections.Connection, rows: Iterable[dict]) -> int:
    cols = "(code, name, region)"
    sql = f"INSERT INTO province {cols} VALUES (%s, %s, %s) ON DUPLICATE KEY UPDATE name=VALUES(name), region=VALUES(region)"
    n = 0
    with conn.cursor() as cur:
        for r in rows:
            cur.execute(sql, (r["code"], r["name"], r.get("region")))
            n += cur.rowcount
    return n


def upsert_aliases(conn: pymysql.connections.Connection, aliases: dict[str, str]) -> int:
    sql = (
        "INSERT INTO school_alias (alias, legal_entity, note) VALUES (%s, %s, %s) "
        "ON DUPLICATE KEY UPDATE legal_entity=VALUES(legal_entity), note=VALUES(note)"
    )
    n = 0
    with conn.cursor() as cur:
        for alias, legal in aliases.items():
            cur.execute(sql, (alias, legal, "研招网按招生单位分列；双一流按法人院校计数"))
            n += cur.rowcount
    return n


_SCHOOL_SQL = """
INSERT INTO school (
  dwdm, sch_id, name, legal_entity, tier, province_code, area, authority,
  is_syl, is_985, is_211, is_self_line, has_grad_school,
  domain, portal_url, portal_score, portal_verified,
  source_level, source_url, fetched_at
) VALUES (
  %(dwdm)s, %(sch_id)s, %(name)s, %(legal_entity)s, %(tier)s, %(province_code)s, %(area)s, %(authority)s,
  %(is_syl)s, %(is_985)s, %(is_211)s, %(is_self_line)s, %(has_grad_school)s,
  %(domain)s, %(portal_url)s, %(portal_score)s, %(portal_verified)s,
  %(source_level)s, %(source_url)s, %(fetched_at)s
)
ON DUPLICATE KEY UPDATE
  sch_id=VALUES(sch_id), name=VALUES(name), legal_entity=VALUES(legal_entity),
  tier=VALUES(tier), province_code=VALUES(province_code), area=VALUES(area),
  authority=VALUES(authority), is_syl=VALUES(is_syl), is_985=VALUES(is_985),
  is_211=VALUES(is_211), is_self_line=VALUES(is_self_line),
  has_grad_school=VALUES(has_grad_school),
  domain=VALUES(domain),
  portal_url=COALESCE(VALUES(portal_url), portal_url),
  portal_score=COALESCE(VALUES(portal_score), portal_score),
  portal_verified=GREATEST(VALUES(portal_verified), portal_verified),
  source_level=VALUES(source_level), source_url=VALUES(source_url), fetched_at=VALUES(fetched_at)
"""


def upsert_schools(conn: pymysql.connections.Connection, records: list[dict]) -> int:
    n = 0
    with conn.cursor() as cur:
        for rec in records:
            cur.execute(_SCHOOL_SQL, rec)
            n += 1
    return n


_PROBE_SQL = """
INSERT INTO school_portal_probe
  (school_id, url, dns_ok, http_status, score, is_best, error, fetched_at)
VALUES (%(school_id)s, %(url)s, %(dns_ok)s, %(http_status)s, %(score)s, %(is_best)s, %(error)s, %(fetched_at)s)
"""


def upsert_probes(
    conn: pymysql.connections.Connection, probes: Sequence[dict]
) -> int:
    """探测记录是证据，不是事实：同一 URL 每次采集都留一行，不做幂等覆盖。"""
    if not probes:
        return 0
    with conn.cursor() as cur:
        # 先清掉这批学校此前的探测痕迹，避免证据无限堆积又无法区分批次
        schools = sorted({p["school_id"] for p in probes})
        placeholders = ",".join(["%s"] * len(schools))
        cur.execute(
            f"DELETE FROM school_portal_probe WHERE school_id IN ({placeholders})", schools
        )
        cur.executemany(_PROBE_SQL, probes)
    return len(probes)


def log_fetch(
    conn: pymysql.connections.Connection,
    *,
    run_id: str,
    dataset: str,
    started_at: datetime,
    rows_fetched: int | None,
    expected_rows: int | None,
    content_hash: str | None,
    baseline_note: str | None,
    outcome: str,
    note: str | None = None,
    target: str | None = None,
) -> None:
    sql = """
    INSERT INTO fetch_log
      (run_id, dataset, target, started_at, finished_at, rows_fetched, expected_rows,
       content_hash, baseline_note, outcome, note)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    ON DUPLICATE KEY UPDATE
      finished_at=VALUES(finished_at), rows_fetched=VALUES(rows_fetched),
      content_hash=VALUES(content_hash), baseline_note=VALUES(baseline_note),
      outcome=VALUES(outcome), note=VALUES(note)
    """
    with conn.cursor() as cur:
        cur.execute(
            sql,
            (
                run_id, dataset, target, started_at, now_utc(), rows_fetched,
                expected_rows, content_hash, baseline_note, outcome, note,
            ),
        )


def school_id_map(conn: pymysql.connections.Connection) -> dict[str, int]:
    """dwdm → school.id"""
    with conn.cursor() as cur:
        cur.execute("SELECT dwdm, id FROM school")
        return {d: i for d, i in cur.fetchall()}


def latest_meta(name: str) -> dict:
    """最近一次同类采集的 _meta 行，用于基线比对与回溯。"""
    files = sorted(_DATA.glob(f"{name}.*.jsonl"))
    if not files:
        return {}
    try:
        with files[-1].open(encoding="utf-8") as fh:
            return json.loads(fh.readline()).get("_meta", {})
    except Exception as exc:  # noqa: BLE001
        log.warning("读取 %s 的 meta 失败：%s", files[-1].name, exc)
        return {}


_DATA = ROOT / "data"