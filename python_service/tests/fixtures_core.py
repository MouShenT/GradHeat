"""Synthetic source fixture; no production records."""
import hashlib
import json

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
