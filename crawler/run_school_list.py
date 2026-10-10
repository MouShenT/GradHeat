"""抓取研招网双一流院校清单（147 所）。

用法：
    python run_school_list.py

机制 9 ⑧ preflight → 采集 → ① 零条拒绝入库 → ③ 基线比对
"""

from __future__ import annotations

import logging
import sys

from gradheat import store, yz
from gradheat.net import Session

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s"
)
log = logging.getLogger("school_list")

SEARCH_URL = "https://yz.chsi.com.cn/sch/search.do?ylgx=1"
PAGE_SIZE = 20
EXPECTED_ROUNDS = 3  # 双一流共 147 所，按 20/页 → 8 页


def preflight(sess: Session) -> None:
    """机制 9 ⑧：开抓前先探测出口与目标响应结构，不信任配置。"""
    log.info("preflight 出口 IP: %s", sess.exit_ip())
    resp = sess.get(SEARCH_URL)
    doc_ok = "sch-item" in resp.text and "js-yxk-yxmc" in resp.text
    log.info("preflight 目标: HTTP %s, 结构校验 %s", resp.status_code, "通过" if doc_ok else "失败")
    if not doc_ok:
        raise RuntimeError("目标页面结构与预期不符，解析器可能已失效 —— 中止采集")


def main() -> int:
    sess = Session(proxy=None)  # 国内站点直连，不继承环境代理
    preflight(sess)

    first = sess.get(SEARCH_URL)
    last_start = yz.max_start(first.text)
    rounds = last_start // PAGE_SIZE + 2  # 最后一页也要抓
    log.info("分页推断：max_start=%d → 共 %d 页", last_start, rounds)

    schools: list[dict] = []
    seen: set[str] = set()

    for page in range(rounds):
        start = 0 if page == 0 else PAGE_SIZE * page
        url = SEARCH_URL if start == 0 else f"{SEARCH_URL}&start={start}"
        resp = first if start == 0 else sess.get(url)
        got = yz.parse_school_list(resp.text, source_url=url)
        fresh = [s for s in got if s["sch_id"] not in seen]
        for s in fresh:
            seen.add(s["sch_id"])
        schools.extend(fresh)
        log.info("第 %d 页 start=%-4s 解析 %d 条（新增 %d）", page + 1, start, len(got), len(fresh))

    warn = store.check_baseline("yz_school_list", len(schools))
    if warn:
        log.error("基线告警：%s", warn)

    path = store.write_jsonl(
        "yz_school_list",
        schools,
        meta={"filter": "ylgx=1 (双一流)", "expected": 147},
    )
    log.info("完成：%d 所 → %s", len(schools), path)
    if len(schools) != 147:
        log.warning("条数与官方双一流院校数（147）不符，需人工复核")
    return 0


if __name__ == "__main__":
    sys.exit(main())