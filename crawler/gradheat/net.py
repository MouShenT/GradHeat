"""HTTP 客户端：显式代理控制 + 限速 + 重试。

设计依据 docs/DESIGN.md 机制 9 ⑪⑫：不继承环境变量代理，出口由调用方显式决定。
"""

from __future__ import annotations

import logging
import random
import time
from dataclasses import dataclass, field

import requests

log = logging.getLogger(__name__)

UA_POOL = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
]


class FetchError(RuntimeError):
    """请求在重试耗尽后仍失败。"""


@dataclass
class Session:
    """带限速与重试的 HTTP 会话。

    proxy=None 时强制直连（trust_env=False），绝不静默走环境变量代理。
    """

    proxy: str | None = None
    min_delay: float = 0.8
    max_delay: float = 2.0
    timeout: float = 25.0
    max_retries: int = 3
    _last_request_at: float = field(default=0.0, init=False)
    _sess: requests.Session = field(default_factory=requests.Session, init=False)

    def __post_init__(self) -> None:
        # 机制 9 ⑪：显式控制代理边界，不继承环境
        self._sess.trust_env = False
        if self.proxy:
            self._sess.proxies = {"http": self.proxy, "https": self.proxy}

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request_at
        wait = random.uniform(self.min_delay, self.max_delay) - elapsed
        if wait > 0:
            time.sleep(wait)

    def get(
        self, url: str, *, referer: str | None = None, raise_status: bool = True, **kw
    ) -> requests.Response:
        """raise_status=False 用于探测场景：4xx/5xx 直接返回响应保留状态码，不进重试。"""
        headers = {"User-Agent": random.choice(UA_POOL), "Accept-Language": "zh-CN,zh;q=0.9"}
        if referer:
            headers["Referer"] = referer
        headers.update(kw.pop("headers", {}))

        last_exc: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            self._throttle()
            try:
                resp = self._sess.get(url, headers=headers, timeout=self.timeout, **kw)
                self._last_request_at = time.monotonic()
                if raise_status:
                    resp.raise_for_status()
                resp.encoding = resp.apparent_encoding or "utf-8"
                return resp
            except Exception as exc:  # noqa: BLE001 - 统一重试
                self._last_request_at = time.monotonic()
                last_exc = exc
                log.warning("请求失败 (%d/%d) %s: %s", attempt, self.max_retries, url, exc)
                if attempt < self.max_retries:
                    time.sleep(1.5 * attempt)

        raise FetchError(f"{url} 重试 {self.max_retries} 次仍失败") from last_exc

    def exit_ip(self) -> str:
        """机制 9 ⑫：用真实请求自证出口，不信任配置文件。"""
        try:
            return self.get("https://myip.ipip.net/").text.strip()
        except Exception as exc:  # noqa: BLE001
            return f"<探测失败: {exc}>"