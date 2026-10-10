"""Offline acceptance against the real frozen export; writes only an isolated test DB."""
import json
import sys
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from gradheat_workbench.app import ROOT, create_app
from gradheat_workbench.repository import digest


def main():
    out = ROOT / ".research/workbench-acceptance-20261005"
    out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as temporary:
        app = create_app(session_db=Path(temporary) / "acceptance.sqlite")
        with TestClient(app, base_url="http://127.0.0.1") as client:
            repo = app.state.repo
            before = digest(repo.data_path)
            meta = client.get("/api/meta").json()
            rows = client.get("/api/programmes").json()
            all_rows = client.get("/api/programmes?eligibility=all").json()
            assert rows["total"] == meta["counts"]["subject_matched_groups"]
            assert rows["units"] == meta["counts"]["subject_matched_units"]
            assert all_rows["total"] == meta["counts"]["programme_source_groups"]
            compared = 0
            for start in range(0, len(rows["items"]), 8):
                items = rows["items"][start:start + 8]
                request = {"title": "自动验收：未知评分边界", "profile": {
                    "target_year": 2027, "modes": ["全日制", "非全日制"], "degrees": ["学术学位", "专业学位"]},
                    "candidates": [{"programme_id": p["id"]} for p in items]}
                response = client.post("/api/compare", json=request)
                assert response.status_code == 200, response.text[:500]
                result = response.json()
                assert result["forecast"] is None and result["approved_release"] is False
                for card in result["cards"]:
                    assert card["hard_constraint_status"] == "pending", card["label"]
                    assert card["ordinary_quota"] is None and card["ranking_pool"] is None
                    s = result["baseline"]["intervals"][card["id"]]
                    assert (s["low"], s["high"], s["specified_weight"]) == (0, 10, 0)
                    assert card["facts"]["programme"] == repo.programmes[card["id"]]
                    assert card["facts"]["history_scope"].startswith("unit-context-only")
                compared += len(result["cards"])
            professional_raw = [p for p in repo.programmes.values() if p.get("degree_type") == "zyxw"]
            professional_filter = client.get("/api/programmes?degree=专业学位&eligibility=all").json()
            filter_ids = {p["id"] for p in professional_filter["items"]}
            assert all(p["id"] in filter_ids for p in professional_raw)
            checked_artifacts = 0
            for sha in repo.artifacts:
                repo.evidence(sha)
                checked_artifacts += 1
            sample = {"title": "自动接口验收（非用户偏好）", "candidates": [{"programme_id": p["id"]} for p in rows["items"][:2]]}
            first = client.post("/api/sessions", json=sample).json()
            second = client.post("/api/sessions", json=sample).json()
            assert first["session_id"] == second["session_id"] and second["reused"]
            assert len(client.get("/api/sessions").json()["items"]) == 1
            sid = first["session_id"]
            loaded = client.get(f"/api/sessions/{sid}").json()
            assert len(loaded["result"]["cards"]) == 2
            assert client.get(f"/api/sessions/{sid}/export?format=md").status_code == 200
            assert client.get(f"/api/sessions/{sid}/export?format=json").json()["session_id"] == sid
            assert digest(repo.data_path) == before
            report = {
                "verification_date": "2026-10-05", "data_as_of": meta["as_of"],
                "snapshot_id": meta["snapshot_id"], "research_batch_id": meta["research_batch_id"],
                "source_sha256": before, "implementation_sha256": app.state.implementation_sha256,
                "programme_source_groups": all_rows["total"], "matched_groups_compared": compared,
                "matched_units": rows["units"], "raw_professional_tags_in_filter": len(professional_raw),
                "original_hashes_checked": checked_artifacts, "snapshot_unchanged": True,
                "unknown_scores_preserved": True, "unknown_quota_preserved": True,
                "save_reload_export": "passed", "repeat_save_zero_growth": True,
                "test_storage": "isolated temporary SQLite; no user sessions written",
                "approved_release": False,
            }
    (out / "real-snapshot.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
