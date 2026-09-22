"""探针：抽样验证「研究生院域名规律」假设，评估能否规模化到 148 所。

假设：多数学校的研招入口是 {yjs,grs,yz,gs,graduate}.<主域>
"""

from __future__ import annotations

import socket
import sys
from concurrent.futures import ThreadPoolExecutor

SAMPLES = [
    ("北京大学", "pku.edu.cn"),
    ("清华大学", "tsinghua.edu.cn"),
    ("浙江大学", "zju.edu.cn"),
    ("复旦大学", "fudan.edu.cn"),
    ("上海交通大学", "sjtu.edu.cn"),
    ("南京大学", "nju.edu.cn"),
    ("武汉大学", "whu.edu.cn"),
    ("中山大学", "sysu.edu.cn"),
    ("哈尔滨工业大学", "hit.edu.cn"),
    ("西安交通大学", "xjtu.edu.cn"),
    ("北京航空航天大学", "buaa.edu.cn"),
    ("华中科技大学", "hust.edu.cn"),
]

PREFIXES = ["yjs", "grs", "yz", "gs", "graduate", "yjsc", "yzb"]


def resolves(host: str) -> bool:
    try:
        socket.getaddrinfo(host, 443, socket.AF_INET)
        return True
    except Exception:  # noqa: BLE001
        return False


def probe(item: tuple[str, str]) -> tuple[str, str, list[str]]:
    name, domain = item
    hits = [f"{p}.{domain}" for p in PREFIXES if resolves(f"{p}.{domain}")]
    return name, domain, hits


with ThreadPoolExecutor(max_workers=12) as ex:
    results = list(ex.map(probe, SAMPLES))

hit_count = 0
for name, domain, hits in results:
    flag = "✅" if hits else "❌"
    if hits:
        hit_count += 1
    print(f"{flag} {name:12} {domain:20} {hits}")

print(f"\n命中率: {hit_count}/{len(SAMPLES)}")