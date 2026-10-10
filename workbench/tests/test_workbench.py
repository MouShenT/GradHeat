import copy
import hashlib
import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from contextlib import closing

from fastapi.testclient import TestClient
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from gradheat_workbench.app import create_app
from gradheat_workbench.decision import evaluate
from gradheat_workbench.models import ComparisonInput, DIMENSIONS
from gradheat_workbench.repository import ResearchRepository
from gradheat_workbench.sessions import SessionStore


def fixture(root):
    folder = root / "snapshot"
    folder.mkdir()
    artifact = folder / "original.html"
    artifact.write_text("原始目录", encoding="utf-8")
    sha = hashlib.sha256(artifact.read_bytes()).hexdigest()
    programmes = [
        {"id": str(i) * 24, "unit": "样本大学", "cohort": 2027, "department": "计算机学院",
         "major_code": code, "major_name": name, "degree_type": degree,
         "mode": mode, "subjects": ["101", "201", "301", "408"] if match else ["101", "204", "302", "408"],
         "eligible_11408": match, "planned_major_raw": "专业：25(不含推免)",
         "planned_numeric_raw": 75, "recommendation_raw": 50,
         "source_sha256": sha, "source_artifact": str(artifact), "source_url": "https://example.edu.cn/catalogue"}
        for i, code, name, degree, mode, match in [
            (1, "081200", "计算机科学与技术", "学术学位", "全日制", True),
            (2, "085404", "计算机技术", "专业学位", "全日制", True),
            (3, "085405", "软件工程", "专业学位", "全日制", False),
            (4, "085410", "人工智能", "专业学位", "非全日制", True),
        ]
    ]
    data = {"target_year": 2027, "as_of": "2026-10-04", "counts": {"units": 1, "subject_matched_groups": 3},
            "units": [{"name": "样本大学", "group": "计算机强校候选"}], "programmes": programmes,
            "checked_claims": [], "history_candidates": [{"unit": "样本大学", "year": 2026, "pool": "其他院系",
                "n": 2, "minimum": 310, "maximum": 350, "mean": 330, "median": 330}],
            "gaps": [{"unit": "样本大学", "year": 2027, "field": "招生人数", "status": "未找到可核验信息"}],
            "evidence": []}
    data_path = folder / "comparison.json"
    data_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    manifest = {"snapshot_id": "fixture-v1", "state": "draft", "outputs": [
        {"path": "comparison.json", "sha256": hashlib.sha256(data_path.read_bytes()).hexdigest()}]}
    (folder / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return folder


def request(ids=(1, 2), scores=None, **kwargs):
    candidates = [{"programme_id": str(i) * 24, "ratings": {d: {"low": scores[i], "high": scores[i]}
                  for d in DIMENSIONS} if scores else {}} for i in ids]
    return ComparisonInput(candidates=candidates, **kwargs)


class DecisionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.folder = fixture(self.root)
        self.repo = ResearchRepository(self.root, self.folder)

    def test_unknown_not_zero_midpoint_or_probability(self):
        result = evaluate(self.repo, request())
        for card in result["cards"]:
            s = result["baseline"]["intervals"][card["id"]]
            self.assertEqual((s["low"], s["high"], s["specified_weight"]), (0, 10, 0))
            self.assertEqual(card["hard_constraint_status"], "pending")
            self.assertIsNone(card["ordinary_quota"])
        self.assertEqual(len(result["baseline"]["potential_best"]), 2)
        self.assertFalse(result["baseline"]["certain_best"])
        self.assertIsNone(result["forecast"])
        self.assertFalse(result["approved_release"])

    def test_partial_rating_retains_unknown_weight(self):
        req = request(ids=(1,)).model_dump()
        req["candidates"][0]["ratings"] = {"research": {"low": 8, "high": 9}}
        score = evaluate(self.repo, ComparisonInput(**req))["baseline"]["intervals"]["1" * 24]
        self.assertAlmostEqual(score["low"], 1.6)
        self.assertAlmostEqual(score["high"], 9.8)
        self.assertEqual(len(score["unknown_dimensions"]), 4)

    def test_robust_preference_and_sensitivity(self):
        result = evaluate(self.repo, request(scores={1: 8, 2: 5}))
        self.assertEqual(result["baseline"]["certain_best"], ["1" * 24])
        self.assertEqual(result["stable_certain_best"], ["1" * 24])
        self.assertEqual(len(result["sensitivity"]), 10)
        self.assertTrue(all(abs(sum(s["normalized_weights"].values()) - 1) < 1e-8 for s in result["sensitivity"]))

    def test_weight_change_reverses_conditional_order(self):
        req = request().model_dump()
        req["weights"] = dict.fromkeys(DIMENSIONS, 0)
        req["weights"].update(research=1.1, location=1)
        req["candidates"][0]["ratings"] = {"research": {"low": 9, "high": 9}, "location": {"low": 1, "high": 1}}
        req["candidates"][1]["ratings"] = {"research": {"low": 1, "high": 1}, "location": {"low": 9, "high": 9}}
        result = evaluate(self.repo, ComparisonInput(**req))
        self.assertEqual(result["baseline"]["certain_best"], ["1" * 24])
        self.assertEqual(result["stable_certain_best"], [])
        self.assertTrue(any(s["certain_best"] == ["2" * 24] for s in result["sensitivity"]))

    def test_known_constraint_failure_excluded(self):
        result = evaluate(self.repo, request(ids=(1, 3, 4), scores={1: 1, 3: 10, 4: 10}))
        self.assertEqual(set(result["baseline"]["intervals"]), {"1" * 24})
        self.assertTrue(all(c["hard_constraint_status"] == "blocked" for c in result["cards"][1:]))

    def test_unknown_mode_and_degree_not_failure(self):
        self.repo.programmes["1" * 24]["degree_type"] = None
        self.repo.programmes["1" * 24]["mode"] = None
        result = evaluate(self.repo, request(ids=(1,)))
        self.assertEqual(result["cards"][0]["hard_constraint_status"], "pending")
        self.assertIn("学习方式待核", result["cards"][0]["qualification_pending"])

    def test_institute_missing_department_can_compare(self):
        del self.repo.programmes["1" * 24]["department"]
        result = evaluate(self.repo, request(ids=(1,)))
        self.assertIn("院系未标", result["cards"][0]["label"])
        self.assertEqual(result["cards"][0]["hard_constraint_status"], "pending")

    def test_user_self_report_does_not_promote_evidence(self):
        req = request(ids=(1,)).model_dump()
        req["candidates"][0]["personal_eligibility"] = "self_reported_pass"
        card = evaluate(self.repo, ComparisonInput(**req))["cards"][0]
        self.assertEqual(card["hard_constraint_status"], "self_reported_pass")
        self.assertEqual(card["application_readiness"], "pending")
        self.assertIsNone(card["ordinary_quota"])
        self.assertIsNone(card["ranking_pool"])

    def test_professional_source_token_and_explicit_name(self):
        self.repo.programmes["2" * 24]["degree_type"] = "zyxw"
        result = evaluate(self.repo, request(ids=(2,)))
        self.assertNotEqual(result["cards"][0]["hard_constraint_status"], "blocked")
        self.assertEqual(self.repo.find(degree="专业学位")["total"], 2)
        self.assertEqual(result["cards"][0]["degree_type"], "专业学位")
        self.assertEqual(result["cards"][0]["facts"]["programme"]["degree_type"], "zyxw")
        self.repo.programmes["2" * 24]["degree_type"] = None
        self.repo.programmes["2" * 24]["major_name"] = "计算机技术（专业学位）"
        self.assertEqual(self.repo.summary(self.repo.programmes["2" * 24])["degree_type"], "专业学位")

    def test_raw_plan_and_history_scope_preserved(self):
        result = evaluate(self.repo, request(ids=(1,)))
        facts = result["cards"][0]["facts"]
        self.assertEqual(facts["programme"]["planned_major_raw"], "专业：25(不含推免)")
        self.assertEqual(facts["history_candidates"][0]["pool"], "其他院系")
        self.assertEqual(facts["history_scope"], "unit-context-only; programme alignment pending")

    def test_invalid_or_nonfinite_input_rejected(self):
        base = request().model_dump()
        bad = []
        zero = copy.deepcopy(base); zero["weights"] = dict.fromkeys(DIMENSIONS, 0); bad.append(zero)
        nan = copy.deepcopy(base); nan["weights"]["cost"] = float("nan"); bad.append(nan)
        reverse = copy.deepcopy(base); reverse["candidates"][0]["ratings"]["cost"] = {"low": 9, "high": 2}; bad.append(reverse)
        duplicate = copy.deepcopy(base); duplicate["candidates"].append(duplicate["candidates"][0]); bad.append(duplicate)
        other_year = copy.deepcopy(base); other_year["profile"]["target_year"] = 2026; bad.append(other_year)
        extra = copy.deepcopy(base); extra["candidates"][0]["ordinary_quota"] = 10; bad.append(extra)
        for value in bad:
            with self.subTest(value=value):
                with self.assertRaises(ValidationError): ComparisonInput(**value)

    def test_snapshot_tamper_rejected(self):
        with (self.folder / "comparison.json").open("a", encoding="utf-8") as stream: stream.write(" ")
        with self.assertRaisesRegex(ValueError, "哈希不符"):
            ResearchRepository(self.root, self.folder)

    def test_original_tamper_rejected(self):
        sha = self.repo.programmes["1" * 24]["source_sha256"]
        self.assertTrue(self.repo.evidence(sha).is_file())
        (self.folder / "original.html").write_text("changed", encoding="utf-8")
        with self.assertRaises(ValueError): self.repo.evidence(sha)

    def test_save_idempotent_and_reopen_immutable(self):
        result = evaluate(self.repo, request())
        path = self.root / "sessions.sqlite"
        store = SessionStore(path)
        first, second = store.save(result), store.save(result)
        self.assertEqual(first["session_id"], second["session_id"])
        self.assertTrue(second["reused"])
        result["input"]["title"] = "下一次比较"
        third = store.save(result)
        self.assertNotEqual(first["session_id"], third["session_id"])
        reopened = SessionStore(path)
        self.assertEqual(len(reopened.list()), 2)
        self.assertEqual(reopened.get(first["session_id"])["result"]["input"]["title"], "我的专业比较")
        self.assertIn("普通统考净名额：未知", reopened.get(first["session_id"])["report_md"])

    def test_json_key_order_does_not_create_new_session(self):
        req = request().model_dump()
        first = evaluate(self.repo, ComparisonInput(**req))
        req["weights"] = dict(reversed(list(req["weights"].items())))
        second = evaluate(self.repo, ComparisonInput(**req))
        store = SessionStore(self.root / "sessions.sqlite")
        a, b = store.save(first), store.save(second)
        self.assertEqual(a["session_id"], b["session_id"])
        self.assertTrue(b["reused"])

    def test_saved_report_tamper_rejected(self):
        store = SessionStore(self.root / "sessions.sqlite")
        row = store.save(evaluate(self.repo, request()))
        with closing(sqlite3.connect(store.path)) as db:
            with db:
                db.execute("UPDATE comparison_session SET report_md='changed'")
        with self.assertRaises(ValueError): store.get(row["session_id"])


class APITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        folder = fixture(self.root)
        self.client = TestClient(create_app(self.root, folder), base_url="http://127.0.0.1")
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)

    def test_filters_and_professional_inclusion(self):
        result = self.client.get("/api/programmes").json()
        self.assertEqual(result["total"], 3)
        result = self.client.get("/api/programmes", params={"degree": "专业学位", "mode": "全日制"}).json()
        self.assertEqual(result["items"][0]["id"], "2" * 24)
        self.assertEqual(self.client.get("/api/programmes", params={"q": "不存在"}).json()["total"], 0)

    def test_compare_save_view_export(self):
        req = request().model_dump()
        compared = self.client.post("/api/compare", json=req)
        self.assertEqual(compared.status_code, 200)
        self.assertEqual(len(compared.json()["implementation_sha256"]), 64)
        first = self.client.post("/api/sessions", json=req).json()
        sid = first["session_id"]
        self.assertTrue(self.client.post("/api/sessions", json=req).json()["reused"])
        self.assertEqual(len(self.client.get("/api/sessions").json()["items"]), 1)
        self.assertEqual(self.client.get(f"/api/sessions/{sid}").json()["result"]["input"], req)
        export = self.client.get(f"/api/sessions/{sid}/export?format=md")
        self.assertIn("专业：25(不含推免)", export.text)
        self.assertIn("attachment", export.headers["content-disposition"])
        self.assertEqual(self.client.get(f"/api/sessions/{sid}/export?format=json").json()["session_id"], sid)

    def test_validation_and_missing_programme(self):
        req = request().model_dump()
        req["candidates"][0]["programme_id"] = "f" * 24
        self.assertEqual(self.client.post("/api/compare", json=req).status_code, 404)
        self.assertEqual(self.client.post("/api/compare", json={}).status_code, 422)
        self.assertEqual(self.client.get("/api/sessions/invalid").status_code, 404)

    def test_local_only_host_and_write_origin(self):
        req = request().model_dump()
        self.assertEqual(self.client.get("/api/meta", headers={"host": "external.invalid"}).status_code, 400)
        self.assertEqual(self.client.post("/api/sessions", json=req, headers={"Origin": "https://external.invalid"}).status_code, 403)
        self.assertEqual(self.client.post("/api/sessions", json=req, headers={"Origin": "http://127.0.0.1"}).status_code, 200)

    def test_static_and_original_attachment(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("/static/admissions.js", response.text)
        self.assertEqual(self.client.get("/static/admissions.js").status_code, 200)
        sha = self.client.get("/api/programmes/" + "1" * 24).json()["programme"]["source_sha256"]
        original = self.client.get("/api/evidence/" + sha)
        self.assertIn("attachment", original.headers["content-disposition"])
        self.assertEqual(original.text, "原始目录")
        self.assertEqual(self.client.get("/api/evidence/" + "0" * 64).status_code, 404)


if __name__ == "__main__":
    unittest.main()
