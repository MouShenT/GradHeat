"""Read immutable research exports. Never mutate or promote admissions facts."""

import hashlib
import json
from collections import Counter
from pathlib import Path


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def source_identity(row: dict) -> tuple:
    # Only a warning about overlapping source versions; not a ranking-pool key.
    return tuple(str(row.get(k) or "") for k in (
        "unit", "cohort", "department", "major_code", "mode", "campus", "comparison_pool_scope"
    ))


def resolve_degree(row: dict) -> tuple[str | None, str]:
    mapping = {"学术学位": "学术学位", "专业学位": "专业学位", "xs": "学术学位",
               "zy": "专业学位", "zyxw": "专业学位", "1": "学术学位", "2": "专业学位"}
    raw = row.get("degree_type")
    if raw in mapping:
        return mapping[raw], f"目录类型字段：{raw}"
    name = row.get("major_name") or ""
    for degree in ("学术学位", "专业学位"):
        if f"（{degree}）" in name or f"({degree})" in name:
            return degree, "专业名称明确标注"
    return None, "未知；未按专业代码推断"


class ResearchRepository:
    def __init__(self, root: Path, snapshot: Path | None = None):
        self.root = root.resolve()
        if snapshot is None:
            pointer = read_json(self.root / ".research/unit-dossiers-20261001/comparison-draft-pointer.json")
            snapshot = Path(pointer["path"])
        self.snapshot = snapshot.resolve()
        self.manifest = read_json(self.snapshot / "manifest.json")
        if self.manifest.get("state") != "draft":
            raise ValueError("此入口只接收研究草稿快照")
        outputs = {entry["path"]: entry["sha256"] for entry in self.manifest["outputs"]}
        self.data_path = self.snapshot / "comparison.json"
        self.data_sha256 = digest(self.data_path)
        if outputs.get("comparison.json") != self.data_sha256:
            raise ValueError("研究快照内容与清单哈希不符，请重新生成快照")
        self.data = read_json(self.data_path)
        if self.data["target_year"] != 2027:
            raise ValueError("工作台当前只支持2027入学资料")
        self.programmes = {row["id"]: row for row in self.data["programmes"]}
        self.units = {row["name"]: row for row in self.data["units"]}
        if len(self.programmes) != len(self.data["programmes"]):
            raise ValueError("快照存在重复专业来源ID")
        if any(p["unit"] not in self.units for p in self.programmes.values()):
            raise ValueError("专业来源单位引用缺失")
        self.identities = Counter(source_identity(row) for row in self.programmes.values())
        self.batch_id = None
        ingest_pointer = self.root / ".research/database-ingest-20261003/latest.json"
        if ingest_pointer.is_file():
            latest = read_json(ingest_pointer)
            manifest = read_json(Path(latest["path"]) / "manifest.json")
            deps = manifest.get("dependencies", [])
            if (manifest.get("source_snapshot") == self.manifest["snapshot_id"]
                    and any(d.get("sha256") == self.data_sha256 for d in deps)):
                self.batch_id = manifest["batch_id"]
        self.artifacts: dict[str, Path] = {}
        for row in self.data.get("evidence", []):
            self._register(row.get("sha256"), row.get("artifact"))
        for row in self.programmes.values():
            self._register(row.get("source_sha256"), row.get("source_artifact"))
            for src in row.get("plan_sources", []):
                self._register(src.get("sha256"), src.get("artifact"))
        for row in self.data.get("history_candidates", []):
            self._register(row.get("source_sha256"), row.get("source_artifact"))
        for row in self.data.get("checked_claims", []):
            for src in row.get("sources", []):
                self._register(src.get("sha256"), src.get("artifact"))

    def _register(self, sha: str | None, filename: str | None):
        if sha and filename:
            path = Path(filename).resolve()
            if path.is_relative_to(self.root):
                self.artifacts[sha] = path

    def meta(self):
        return {
            "snapshot_id": self.manifest["snapshot_id"], "source_sha256": self.data_sha256,
            "research_batch_id": self.batch_id, "as_of": self.data["as_of"],
            "target_year": self.data["target_year"], "state": "draft",
            "counts": self.data["counts"], "dimensions": {
                "research": "研究兴趣", "location": "城市与生活", "cost": "费用可承受度",
                "career": "就业与发展", "training": "培养方式适配"
            },
            "groups": sorted({u["group"] for u in self.units.values()}),
            "modes": sorted({p.get("mode") for p in self.programmes.values()} - {"", None}),
        }

    def summary(self, row: dict):
        out = {key: row.get(key) for key in (
            "id", "unit", "cohort", "department", "major_code", "major_name", "degree_type",
            "mode", "campus", "comparison_pool_scope", "subjects", "eligible_11408",
            "planned_major_raw", "publication_stage", "directions", "source_url", "source_sha256"
        )}
        out["group"] = self.units[row["unit"]]["group"]
        out["degree_type"], out["degree_type_basis"] = resolve_degree(row)
        out["degree_type_original"] = row.get("degree_type")
        out["source_versions"] = self.identities[source_identity(row)]
        return out

    def find(self, query="", group="", mode="", degree="", eligibility="matched"):
        rows = []
        for p in self.programmes.values():
            if eligibility == "matched" and p.get("eligible_11408") is not True:
                continue
            if group and self.units[p["unit"]]["group"] != group:
                continue
            if mode and p.get("mode") != mode:
                continue
            if degree and resolve_degree(p)[0] != degree:
                continue
            text = " ".join(str(p.get(k) or "") for k in (
                "unit", "department", "major_code", "major_name", "campus", "comparison_pool_scope"
            ))
            if query.strip().casefold() not in text.casefold():
                continue
            rows.append(self.summary(p))
        return {"items": rows, "total": len(rows), "units": len({p["unit"] for p in rows})}

    def detail(self, programme_id: str):
        p = self.programmes[programme_id]
        unit = p["unit"]
        return {
            "programme": p, "display": self.summary(p), "source_versions": self.identities[source_identity(p)],
            "unit": self.units[unit],
            "checked_claims": [c for c in self.data["checked_claims"] if c["unit"] == unit],
            "history_candidates": [h for h in self.data["history_candidates"] if h["unit"] == unit],
            "gaps": [g for g in self.data["gaps"] if g["unit"] == unit],
            "history_scope": "unit-context-only; programme alignment pending",
        }

    def evidence(self, sha: str) -> Path:
        path = self.artifacts[sha]
        if not path.is_file():
            raise FileNotFoundError("原件文件缺失")
        if digest(path) != sha:
            raise ValueError("原件内容与记录哈希不符")
        return path
