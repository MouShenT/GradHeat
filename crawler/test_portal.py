"""P0.1 修复的离线验证测试（不发真实网络请求）。

对应 docs/DECISION-REVIEW.md §8 离线复现的三项：
  1. 「缺少校名和研究生关键词，仅 yz 子域 + 招生：评分 6，通过阈值 5」→ 修复后必须不合格
  2. best=None 的失败结果映射 AttributeError → 修复后必须不崩溃
  3. tried / DNS / 探测时间证据必须完整留存
"""

from __future__ import annotations

import unittest

import run_find_portal
from gradheat import portal


class FakeResp:
    def __init__(self, url: str, status: int, text: str):
        self.url = url
        self.status_code = status
        self.text = text


class FakeSession:
    """url -> FakeResp 或 Exception；记录调用顺序。"""

    def __init__(self, responses: dict):
        self.responses = responses
        self.calls: list[str] = []

    def get(self, url: str, **kw):
        self.calls.append(url)
        v = self.responses[url]
        if isinstance(v, Exception):
            raise v
        return v


def fake_resolver(mapping: dict[str, bool]):
    return lambda domain: {f"{p}.{domain}": mapping.get(p, False) for p in portal.PREFIXES}


QINGHUA = "清华大学"
QINGHUA_DOMAIN = "tsinghua.edu.cn"


class CheckHardConditionsTest(unittest.TestCase):
    """DECISION-REVIEW 离线复现第 1 项：评分达标但缺身份/用途，不得通过。"""

    def test_yz_subdomain_with_zhaosheng_only_rejected(self):
        # 旧实现：yz 子域 4 分 + 招生 2 分 = 6 ≥ 阈值 5，误判为已验证
        text = "欢迎访问招生信息网"  # 无校名、无「研究生」
        qualified, reasons, score = portal._check(
            200, "https://yz.some.edu.cn/", text, "某大学", "some.edu.cn"
        )
        self.assertIn("identity:页面无校名", reasons)
        self.assertIn("purpose:页面无研究生关键词", reasons)
        self.assertFalse(qualified)
        self.assertGreaterEqual(score, 6)  # 分数照旧很高 —— 但不再决定资格

    def test_identity_only_rejected(self):
        qualified, reasons, _ = portal._check(
            200, "https://www.some.edu.cn/", "清华大学", "清华大学", "some.edu.cn"
        )
        self.assertFalse(qualified)
        self.assertIn("purpose:页面无研究生关键词", reasons)

    def test_grad_page_without_school_name_rejected(self):
        # 通用研究生站（非该校）必须被落地域 + 身份双重拒绝
        qualified, reasons, _ = portal._check(
            200, "https://yz.other-site.com/", "研究生招生信息网", "清华大学", "tsinghua.edu.cn"
        )
        self.assertFalse(qualified)
        self.assertIn("identity:页面无校名", reasons)
        self.assertIn("landing:落地域非本校主域", reasons)

    def test_non_2xx_rejected(self):
        qualified, reasons, _ = portal._check(
            403, "https://yz.tsinghua.edu.cn/", "清华大学 研究生招生", QINGHUA, QINGHUA_DOMAIN
        )
        self.assertFalse(qualified)
        self.assertIn("status:HTTP 403", reasons)

    def test_legitimate_page_qualified(self):
        text = f"{QINGHUA}研究生招生 欢迎报考"
        qualified, reasons, score = portal._check(
            200, "https://yz.tsinghua.edu.cn/", text, QINGHUA, QINGHUA_DOMAIN
        )
        self.assertTrue(qualified)
        self.assertEqual(reasons, [])
        self.assertEqual(score, 3 + 2 + 4)

    def test_landing_on_subdomain_ok(self):
        # 落地到主域的子域（含重定向后）合格
        self.assertTrue(portal._landing_ok("https://www.tsinghua.edu.cn/", QINGHUA_DOMAIN))
        self.assertTrue(portal._landing_ok("https://yz.tsinghua.edu.cn/", QINGHUA_DOMAIN))
        self.assertFalse(portal._landing_ok("https://tsinghua.com.cn/", QINGHUA_DOMAIN))
        self.assertFalse(portal._landing_ok("https://evil-tsinghua.edu.cn.hacker.com/", QINGHUA_DOMAIN))


class ProbeSchoolTest(unittest.TestCase):
    def _probe(self, session, resolver):
        return portal.probe_school(QINGHUA, QINGHUA_DOMAIN, session, resolver=resolver)

    def test_qualified_best_selected_with_evidence(self):
        url = "https://yz.tsinghua.edu.cn/"
        text = f"{QINGHUA}研究生招生信息网"
        result = self._probe(
            FakeSession({url: FakeResp(url, 200, text)}),
            fake_resolver({"yz": True, "yjs": False}),
        )
        self.assertTrue(result["verified"])
        self.assertEqual(result["best"]["url"], url)
        self.assertEqual(result["best"]["qualified"], True)
        # 证据留存：DNS 结果（含失败项）、tried 带 probed_at
        self.assertEqual(result["dns"]["yz.tsinghua.edu.cn"], True)
        self.assertEqual(result["dns"]["yjs.tsinghua.edu.cn"], False)
        self.assertEqual(len(result["tried"]), 1)
        self.assertIn("probed_at", result["tried"][0])
        self.assertTrue(result["probed_at"])

    def test_all_unqualified_yields_best_none(self):
        url = "https://yz.tsinghua.edu.cn/"
        result = self._probe(
            FakeSession({url: FakeResp(url, 200, "仅招生两个字")}),
            fake_resolver({"yz": True}),
        )
        self.assertIsNone(result["best"])
        self.assertFalse(result["verified"])
        # 失败原因进了证据
        self.assertIn("identity:页面无校名", result["tried"][0]["fail_reasons"])

    def test_dns_all_fail_no_http_issued(self):
        sess = FakeSession({})
        result = self._probe(sess, fake_resolver({}))
        self.assertFalse(result["verified"])
        self.assertEqual(sess.calls, [])  # DNS 全挂就不发 HTTP
        self.assertEqual(result["candidates"], [])
        self.assertEqual(result["tried"], [])

    def test_http_exception_recorded_not_fatal(self):
        url = "https://yz.tsinghua.edu.cn/"
        sess = FakeSession({url: RuntimeError("connection timed out")})
        result = self._probe(sess, fake_resolver({"yz": True}))
        self.assertFalse(result["verified"])
        self.assertEqual(len(result["tried"]), 2)  # https 和 http 两次尝试都记 err
        self.assertIn("err", result["tried"][0])

    def test_http_fallback_after_https_fails(self):
        http_url = "http://yz.tsinghua.edu.cn/"
        text = f"{QINGHUA}研究生招生"
        sess = FakeSession(
            {
                "https://yz.tsinghua.edu.cn/": RuntimeError("tls handshake failed"),
                http_url: FakeResp(http_url, 200, text),
            }
        )
        result = self._probe(sess, fake_resolver({"yz": True}))
        self.assertTrue(result["verified"])
        self.assertEqual(result["best"]["url"], http_url)
        self.assertEqual(result["tried"][0]["err"], "tls handshake failed")


class BuildRowsNoCrashTest(unittest.TestCase):
    """DECISION-REVIEW 离线复现第 2 项：best=None 时 .get() 链上不再 AttributeError。"""

    YZ = [{"name": QINGHUA, "dwdm": "10003"}, {"name": "X大学", "dwdm": "99999"}]

    def test_probe_result_missing_for_school(self):
        rows = run_find_portal.build_rows(
            self.YZ, [], {QINGHUA: QINGHUA_DOMAIN}, {}, set(), set(), "run1"
        )
        self.assertEqual(len(rows), 2)
        self.assertIsNone(rows[0]["portal_url"])
        self.assertFalse(rows[0]["portal_verified"])
        self.assertEqual(rows[0]["portal_tried"], [])

    def test_best_none_result_row(self):
        results = [
            {
                "school": QINGHUA,
                "domain": QINGHUA_DOMAIN,
                "dns": {"yz.tsinghua.edu.cn": True},
                "candidates": ["yz.tsinghua.edu.cn"],
                "tried": [{"url": "https://yz.tsinghua.edu.cn/", "ok": False, "err": "x"}],
                "best": None,
                "verified": False,
                "probed_at": "2026-09-23T01:02:03+00:00",
            }
        ]
        rows = run_find_portal.build_rows(
            self.YZ, results, {QINGHUA: QINGHUA_DOMAIN}, {}, set(), set(), "run1"
        )
        # 旧实现在此触发 AttributeError
        self.assertIsNone(rows[0]["portal_url"])
        self.assertIsNone(rows[0]["portal_score"])
        self.assertFalse(rows[0]["portal_verified"])
        self.assertEqual(rows[0]["portal_tried"], results[0]["tried"])
        self.assertEqual(rows[0]["portal_dns"], results[0]["dns"])
        self.assertEqual(rows[0]["probed_at"], "2026-09-23T01:02:03+00:00")
        self.assertEqual(rows[0]["run_id"], "run1")

    def test_verified_result_row(self):
        results = [
            {
                "school": QINGHUA,
                "domain": QINGHUA_DOMAIN,
                "dns": {},
                "candidates": ["yz.tsinghua.edu.cn"],
                "tried": [],
                "best": {
                    "url": "https://yz.tsinghua.edu.cn/",
                    "status": 200,
                    "score": 9,
                    "qualified": True,
                },
                "verified": True,
                "probed_at": "2026-09-23T01:02:03+00:00",
            }
        ]
        rows = run_find_portal.build_rows(
            self.YZ, results, {QINGHUA: QINGHUA_DOMAIN}, {}, set(), set(), "run1"
        )
        self.assertEqual(rows[0]["portal_url"], "https://yz.tsinghua.edu.cn/")
        self.assertTrue(rows[0]["portal_verified"])
        self.assertEqual(rows[0]["portal_score"], 9)

    def test_probe_error_field_preserved(self):
        results = [
            {
                "school": QINGHUA,
                "domain": QINGHUA_DOMAIN,
                "dns": {},
                "candidates": [],
                "tried": [],
                "best": None,
                "verified": False,
                "probed_at": "2026-09-23T01:02:03+00:00",
                "error": "probe crashed",
            }
        ]
        rows = run_find_portal.build_rows(
            self.YZ, results, {QINGHUA: QINGHUA_DOMAIN}, {}, set(), set(), "run1"
        )
        self.assertEqual(rows[0]["portal_probe_error"], "probe crashed")


class ResolveCandidatesTest(unittest.TestCase):
    def test_resolver_shape(self):
        # 只验证返回结构（host -> bool，覆盖全部前缀），真实解析已由线上探测验证
        out = portal.resolve_candidates("example.invalid")
        self.assertEqual(set(out), set(portal.candidates("example.invalid")))
        self.assertTrue(all(v is False for v in out.values()))


if __name__ == "__main__":
    unittest.main()
