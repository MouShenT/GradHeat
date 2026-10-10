"""定位各校研究生招生网站。

策略（两阶段，避免对 148×N 个候选做无节制 HTTP 请求）：
  阶段 1  DNS 解析候选子域（并发、整体限时 —— getaddrinfo 无原生超时，挂住的解析不能拖死整批）
  阶段 2  对解析成功的候选发 HTTP（快速失败：单次重试、10s 超时、4xx/5xx 不重试直接留状态码）

验证硬条件（P0.1：三者缺一不可，分数只在通过硬条件的候选中排序）：
  身份    页面文本含校名核心词（去括号校区后缀的全名）
  用途    页面文本含「研究生」
  落地域  HTTP 2xx，且最终落地 host 属于该校主域（== domain 或其子域）

机制 9 ④：健康检查必须校验响应结构，不能只看「能连上」。
每个候选的 DNS、HTTP 状态与失败原因都进 dns/tried 证据，不静默丢弃。
"""

from __future__ import annotations

import logging
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from urllib.parse import urlparse

from .net import Session

log = logging.getLogger(__name__)

PREFIXES = ["yz", "yjs", "grs", "gs", "graduate", "yzb", "zs", "yjsy", "yjszs", "yzs"]
SCHEMES = ("https", "http")
DNS_TIMEOUT = 5.0
PROBE_TIMEOUT = 10.0
PROBE_RETRIES = 1


def candidates(domain: str) -> list[str]:
    return [f"{p}.{domain}" for p in PREFIXES]


def resolve_candidates(domain: str, *, timeout: float = DNS_TIMEOUT) -> dict[str, bool]:
    """并发解析全部候选子域，整体限时 timeout 秒，返回 host -> 是否解析成功。

    getaddrinfo 无原生超时，用守护线程限时：挂住的解析不拖死批次，也不阻塞进程退出。
    """
    hosts = candidates(domain)
    done: dict[str, bool] = {}

    def check(host: str) -> None:
        try:
            socket.getaddrinfo(host, 443, socket.AF_INET, socket.SOCK_STREAM)
            done[host] = True
        except Exception:  # noqa: BLE001
            done[host] = False

    threads = [threading.Thread(target=check, args=(h,), daemon=True) for h in hosts]
    for t in threads:
        t.start()
    deadline = time.monotonic() + timeout
    for t in threads:
        t.join(max(0.0, deadline - time.monotonic()))
    return {h: done.get(h, False) for h in hosts}


def _core_name(name: str) -> str:
    """校名核心词，用于身份硬校验。'北京大学' -> '北京大学'；去掉括号校区后缀。"""
    return name.split("(")[0]


def _landing_ok(final_url: str, domain: str) -> bool:
    host = (urlparse(final_url).hostname or "").lower()
    return host == domain or host.endswith("." + domain)


def _score(final_url: str, text: str) -> int:
    """排序分：越像「研究生招生」入口越高。不做资格判定 —— 资格由硬条件决定。"""
    score = 0
    host = urlparse(final_url).hostname or ""

    if "研究生" in text:
        score += 3
    if "招生" in text:
        score += 2

    label = host.split(".")[0]
    if label in ("yz", "yzb", "yjszs", "yzs"):
        score += 4  # 研究生招生
    elif label in ("yjs", "yjsy", "grs", "gs", "graduate"):
        score += 2  # 研究生院

    return score


def _check(
    status: int, final_url: str, text: str, school: str, domain: str
) -> tuple[bool, list[str], int]:
    """硬条件核验。返回 (是否合格, 失败原因列表, 排序分)。"""
    reasons: list[str] = []
    if not 200 <= status < 300:
        reasons.append(f"status:HTTP {status}")
    if _core_name(school) not in text:
        reasons.append("identity:页面无校名")
    if "研究生" not in text:
        reasons.append("purpose:页面无研究生关键词")
    if not _landing_ok(final_url, domain):
        reasons.append("landing:落地域非本校主域")
    return (not reasons), reasons, _score(final_url, text)


def probe_school(school: str, domain: str, sess: Session, *, resolver=resolve_candidates) -> dict:
    """返回该 school 的研究生招生入口候选、证据与最佳匹配。

    best 只在通过硬条件的候选中选最高分；全部不合格时 best=None（明确未验证，不假装成功）。
    """
    probed_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    dns = resolver(domain)
    hosts = [h for h, ok in dns.items() if ok]

    tried: list[dict] = []
    best: dict | None = None

    for host in hosts:
        for scheme in SCHEMES:
            url = f"{scheme}://{host}/"
            try:
                resp = sess.get(url, raise_status=False)
            except Exception as exc:  # noqa: BLE001
                tried.append(
                    {"url": url, "ok": False, "err": str(exc)[:120], "probed_at": probed_at}
                )
                continue
            text = resp.text[:60000]
            qualified, reasons, sc = _check(
                resp.status_code, str(resp.url), text, school, domain
            )
            rec = {
                "url": str(resp.url),
                "requested_url": url,
                "status": resp.status_code,
                "score": sc,
                "qualified": qualified,
                "fail_reasons": reasons,
                "probed_at": probed_at,
            }
            tried.append(rec)
            if qualified and (best is None or sc > best["score"]):
                best = rec
            break  # 该 host 成功一次即可

    return {
        "school": school,
        "domain": domain,
        "dns": dns,
        "candidates": hosts,
        "tried": tried,
        "best": best,
        "verified": best is not None,
        "probed_at": probed_at,
    }


def probe_all(
    school_domains: dict[str, str],
    *,
    workers: int = 6,
    delay: float = 0.3,
    progress_every: int = 10,
) -> list[dict]:
    """并发探测。requests.Session 非线程安全 —— 每线程各持一个。

    单校异常不中断整批：失败校返回 error 字段与空证据，其余学校继续。
    """
    local = threading.local()

    def sess_for_thread() -> Session:
        s = getattr(local, "sess", None)
        if s is None:
            # 探测场景快速失败：单次重试 + 10s 超时；慢重试留给正式内容采集
            s = Session(
                proxy=None,
                min_delay=delay,
                max_delay=delay + 0.4,
                timeout=PROBE_TIMEOUT,
                max_retries=PROBE_RETRIES,
            )
            local.sess = s
        return s

    total = len(school_domains)
    done = [0]
    lock = threading.Lock()

    def work(item: tuple[str, str]) -> dict:
        name, dom = item
        probed_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        try:
            result = probe_school(name, dom, sess_for_thread())
        except Exception as exc:  # noqa: BLE001
            log.error("探测失败 %s: %s", name, exc)
            result = {
                "school": name,
                "domain": dom,
                "dns": {},
                "candidates": [],
                "tried": [],
                "best": None,
                "verified": False,
                "probed_at": probed_at,
                "error": str(exc)[:120],
            }
        with lock:
            done[0] += 1
            if done[0] % progress_every == 0 or done[0] == total:
                log.info("探测进度：%d/%d", done[0], total)
        return result

    with ThreadPoolExecutor(max_workers=workers) as ex:
        return list(ex.map(work, school_domains.items()))
