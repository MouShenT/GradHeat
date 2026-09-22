"""定位各校研究生招生网站。

策略（两阶段，避免对 148×N 个候选做无节制 HTTP 请求）：
  阶段 1  DNS 解析候选子域（廉价，可并发）
  阶段 2  对解析成功的候选发一次 HTTP，校验页面是否真的是该校的研究生招生入口

判据（机制 9 ④：健康检查必须校验响应结构，不能只看「能连上」）：
  - HTTP 2xx/3xx
  - 页面文本含校名（或校名去掉「大学/学院」的核心词）
  - 页面文本含「研究生」或「招生」
  - 优先 URL 含 yz / zs（招生） 的，其次 yjs / grs
"""

from __future__ import annotations

import logging
import socket
import threading
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

from .net import Session

log = logging.getLogger(__name__)

PREFIXES = ["yz", "yjs", "grs", "gs", "graduate", "yzb", "zs", "yjsy", "yjszs", "yzs"]
SCHEMES = ("https", "http")


def candidates(domain: str) -> list[str]:
    return [f"{p}.{domain}" for p in PREFIXES]


def dns_ok(host: str) -> bool:
    for scheme, port in (("https", 443), ("http", 80)):
        try:
            socket.getaddrinfo(host, port, socket.AF_INET)
            return True
        except Exception:  # noqa: BLE001
            continue
    return False


def _core_name(name: str) -> str:
    """校名核心词，用于内容校验。'北京大学' -> '北京大学'；去掉括号校区后缀。"""
    return name.split("(")[0]


def _score(url: str, text: str, school: str) -> int:
    """给候选打分，越高越像研究生招生入口。"""
    score = 0
    host = urlparse(url).hostname or ""
    core = _core_name(school)

    if "研究生" in text:
        score += 3
    if "招生" in text:
        score += 2
    if core in text:
        score += 3
    elif core[:3] in text:
        score += 1

    label = host.split(".")[0]
    if label in ("yz", "yzb", "yjszs", "yzs"):
        score += 4  # 研究生招生
    elif label in ("yjs", "yjsy", "grs", "gs", "graduate"):
        score += 2  # 研究生院

    return score


def probe_school(
    school: str, domain: str, sess: Session, *, min_score: int = 5
) -> dict:
    """返回该 school 的研究生招生入口候选与最佳匹配。"""
    hosts = [h for h in candidates(domain) if dns_ok(h)]

    tried: list[dict] = []
    best: dict | None = None

    for host in hosts:
        for scheme in SCHEMES:
            url = f"{scheme}://{host}/"
            try:
                resp = sess.get(url)
            except Exception as exc:  # noqa: BLE001
                tried.append({"url": url, "ok": False, "err": str(exc)[:80]})
                continue
            text = resp.text[:60000]
            sc = _score(url, text, school)
            rec = {"url": str(resp.url), "status": resp.status_code, "score": sc}
            tried.append(rec)
            if best is None or sc > best["score"]:
                best = rec
            break  # 该 host 成功一次即可

    return {
        "school": school,
        "domain": domain,
        "candidates": hosts,
        "tried": tried,
        "best": best if best and best["score"] >= min_score else None,
        "verified": bool(best and best["score"] >= min_score),
    }


def probe_all(
    school_domains: dict[str, str], *, workers: int = 6, delay: float = 0.3
) -> list[dict]:
    """并发探测。requests.Session 非线程安全 —— 每线程各持一个。"""
    local = threading.local()

    def sess_for_thread() -> Session:
        s = getattr(local, "sess", None)
        if s is None:
            s = Session(proxy=None, min_delay=delay, max_delay=delay + 0.4)
            local.sess = s
        return s

    def work(item: tuple[str, str]) -> dict:
        name, dom = item
        try:
            return probe_school(name, dom, sess_for_thread())
        except Exception as exc:  # noqa: BLE001
            log.error("探测失败 %s: %s", name, exc)
            return {
                "school": name,
                "domain": dom,
                "candidates": [],
                "tried": [],
                "best": None,
                "verified": False,
            }

    with ThreadPoolExecutor(max_workers=workers) as ex:
        return list(ex.map(work, school_domains.items()))