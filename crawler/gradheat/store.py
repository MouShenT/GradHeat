"""落盘：JSONL + 采集元数据。

机制 9 ①②③：每次采集必须带 fetched_count，抓到 0 条必须告警而非静默入库。
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

log = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


class EmptyResultError(RuntimeError):
    """抓到 0 条。机制 9 ①：绝不当作「真的没有」入库。"""


def snapshot_path(name: str) -> Path:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return DATA_DIR / f"{name}.{stamp}.jsonl"


def write_jsonl(name: str, rows: Iterable[dict[str, Any]], *, meta: dict[str, Any]) -> Path:
    """写出带元数据头的 JSONL。条数为 0 时抛 EmptyResultError。"""
    rows = list(rows)
    if not rows:
        raise EmptyResultError(f"{name}: 抓到 0 条 —— 按机制 9 ① 拒绝入库，需人工复核")

    path = snapshot_path(name)
    fetched_at = datetime.now(timezone.utc).isoformat()
    payload = []
    for row in rows:
        row = dict(row)
        row["_fetched_at"] = fetched_at
        row["_source"] = name
        payload.append(row)

    with path.open("w", encoding="utf-8") as fh:
        header = {
            "_meta": {
                "source": name,
                "fetched_count": len(payload),
                "fetched_at": fetched_at,
                "content_hash": hashlib.sha256(
                    json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()
                ).hexdigest()[:16],
                **meta,
            }
        }
        fh.write(json.dumps(header, ensure_ascii=False) + "\n")
        for row in payload:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    log.info("写入 %s（%d 条）", path.name, len(payload))
    return path


def check_baseline(name: str, count: int, *, drop_ratio: float = 0.2) -> str | None:
    """机制 9 ③：与最近一次快照的条数比对，断崖式下跌返回告警文本。"""
    if not DATA_DIR.exists():
        return None
    snaps = sorted(DATA_DIR.glob(f"{name}.*.jsonl"))
    if not snaps:
        return None
    latest = snaps[-1]
    try:
        with latest.open(encoding="utf-8") as fh:
            prev = json.loads(fh.readline())["_meta"]["fetched_count"]
    except Exception:  # noqa: BLE001
        return None
    if prev and count < prev * (1 - drop_ratio):
        return f"{name}: 条数从 {prev} 跌至 {count}（-{100 * (1 - count / prev):.0f}%），需人工复核"
    return None