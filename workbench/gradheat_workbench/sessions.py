"""Append-only local comparison sessions, independent from research MySQL."""

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from .models import DIMENSIONS


def canonical(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def render_report(result: dict) -> str:
    source, request = result["source"], result["input"]
    lines = [f"# {request['title']}", "", "状态：个人比较草稿；不是正式择校推荐或录取预测。", "",
             f"目标：{source['target_year']}入学 / 101+201+301+408", f"资料截至：{source['as_of']}",
             f"来源快照：{source['snapshot_id']}", f"来源JSON SHA256：{source['source_sha256']}",
             f"研究MySQL批次：{source.get('research_batch_id') or '未关联'}",
             f"算法：{result['analysis_version']}", f"实现SHA256：{result.get('implementation_sha256', '未记录')}",
             "", "## 本次输入", "", f"学习方式：{'、'.join(request['profile']['modes'])}",
             f"学位类型：{'、'.join(request['profile']['degrees'])}",
             f"个人备注：{request['profile']['notes'] or '未填写'}", "",
             "权重（用户输入；默认相等只用于开始填写）："]
    for d, label in DIMENSIONS.items():
        lines.append(f"- {label}：{request['weights'][d]}")
    lines.extend(["", "## 比较项目", ""])
    status = {"blocked": "不符合本次筛选条件", "pending": "资格待核", "self_reported_pass": "用户自报资格满足（未审核）"}
    for card in result["cards"]:
        p = card["facts"]["programme"]
        score = result["baseline"]["intervals"].get(card["id"])
        lines.extend([f"### {card['label']}", "", f"来源ID：{card['id']}",
                      f"资格：{status[card['hard_constraint_status']]}",
                      f"学位/方式/校区：{card.get('degree_type') or '未知'} / {p.get('mode') or '未知'} / {p.get('campus') or '未核'}",
                      f"学位类型展示依据：{card.get('degree_type_basis') or '未记录'}；原字段：{p.get('degree_type')}",
                      f"原文计划：{p.get('planned_major_raw') if p.get('planned_major_raw') is not None else '未知'}",
                      "普通统考净名额：未知；2027实际排序范围：未验收。",
                      f"计划口径：{p.get('quota_definition') or p.get('quota_scope') or '待核'}",
                      f"目录核验状态：{p.get('verification') or '提取草稿'}",
                      f"目录原文：{p.get('source_url') or '未记录'}",
                      f"目录原件SHA256：{p.get('source_sha256') or '未记录'}",
                      f"原文位置：{'; '.join(p.get('locators') or [p.get('locator') or '待核'])}",
                      f"偏好区间：{score['low']}—{score['high']} / 10" if score else "偏好计算：已排除",
                      f"项目备注：{card['notes'] or '未填写'}", ""])
        for reason in card["blocked_reasons"] + card["qualification_pending"]:
            lines.append(f"- {reason}")
        for d, label in DIMENSIONS.items():
            r = card["ratings"].get(d)
            lines.append(f"- {label}：{r['low']}—{r['high']}（依据：{r['basis'] or '未填写'}）" if r else f"- {label}：未知[0,10]")
        lines.extend(["", "该单位已核对原文资料（需另核是否适用于本项目）：", ""])
        claims = card["facts"]["checked_claims"]
        for claim in claims:
            lines.append(f"- {claim.get('year') or claim.get('cohort')} / {claim.get('pool', '')}：{claim['claim']}")
            lines.append(f"  限制：{claim.get('limitation') or '适用范围待核'}")
            for src in claim.get("sources", []):
                lines.append(f"  原文：{src.get('url')}；SHA256：{src.get('sha256')}；位置：{src.get('locator')}")
        if not claims:
            lines.append("未取得对应核对资料。")
        lines.extend(["", "该单位历史统计候选（不自动匹配本项目，不代表全部报考者）：", ""])
        for h in card["facts"]["history_candidates"]:
            lines.append(f"- {h['year']} / {h.get('pool')} / {h.get('special')}；n={h.get('n')}，"
                         f"初试最低/最高={h.get('minimum')}/{h.get('maximum')}，均值/中位={h.get('mean')}/{h.get('median')}。")
            lines.append(f"  原文：{h.get('source_url')}；SHA256：{h.get('source_sha256')}；核验：{h.get('verification')}")
        if not card["facts"]["history_candidates"]:
            lines.append("未取得对应统计候选。")
        lines.extend(["", "该单位资料缺失：", ""])
        for gap in card["facts"]["gaps"]:
            lines.append(f"- {gap['year']} {gap['field']}：{gap['status']}")
        if not card["facts"]["gaps"]:
            lines.append("当前下载缺失表无此单位条目；不代表范围和口径全部验收。")
        lines.append("")
    labels = {c["id"]: c["label"] for c in result["cards"]}
    fmt = lambda ids: "；".join(labels[i] for i in ids) or "没有可确定的项目"
    lines.extend(["## 偏好敏感性", "", "确定最优表示在本次偏好区间内不低于其余候选；仍以资格成立为前提。", "",
                  f"基准可能最优：{fmt(result['baseline']['potential_best'])}",
                  f"基准确定最优：{fmt(result['baseline']['certain_best'])}",
                  f"在本轮有限权重测试中均为确定最优：{fmt(result['stable_certain_best'])}", ""])
    for s in result["sensitivity"]:
        lines.append(f"- {DIMENSIONS[s['dimension']]}权重×{s['factor']}：可能最优={fmt(s['potential_best'])}；确定最优={fmt(s['certain_best'])}")
    lines.extend(["", "## 假设与解释", "", result["interpretation"], ""])
    lines.extend(f"- {a}" for a in result["assumptions"])
    lines.extend(["", "热度、报名需求和录取概率均未计算。", ""])
    return "\n".join(lines)


class SessionStore:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS comparison_session (
                session_id TEXT PRIMARY KEY, created_at TEXT NOT NULL,
                title TEXT NOT NULL, snapshot_id TEXT NOT NULL,
                analysis_version TEXT NOT NULL, candidate_count INTEGER NOT NULL,
                result_json TEXT NOT NULL, report_md TEXT NOT NULL)""")

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def save(self, result: dict):
        payload = canonical(result)
        report = render_report(result)
        session_id = hashlib.sha256(canonical({"result": result, "report_md": report}).encode("utf-8")).hexdigest()
        created_at = datetime.now(timezone.utc).isoformat()
        with self.connect() as db:
            cur = db.execute("INSERT OR IGNORE INTO comparison_session VALUES (?,?,?,?,?,?,?,?)", (
                session_id, created_at, result["input"]["title"], result["source"]["snapshot_id"],
                result["analysis_version"], len(result["cards"]), payload, report
            ))
            reused = cur.rowcount == 0
        return {"session_id": session_id, "reused": reused, **self.get(session_id, summary=True)}

    def get(self, session_id: str, summary=False):
        with self.connect() as db:
            row = db.execute("SELECT * FROM comparison_session WHERE session_id=?", (session_id,)).fetchone()
        if row is None:
            raise KeyError(session_id)
        content = {"result": json.loads(row["result_json"]), "report_md": row["report_md"]}
        if hashlib.sha256(canonical(content).encode("utf-8")).hexdigest() != session_id:
            raise ValueError("保存的比较记录内容校验失败")
        out = {k: row[k] for k in ("session_id", "created_at", "title", "snapshot_id", "analysis_version", "candidate_count")}
        if not summary:
            out["result"] = content["result"]
            out["report_md"] = row["report_md"]
        return out

    def list(self):
        with self.connect() as db:
            rows = db.execute("""SELECT session_id,created_at,title,snapshot_id,analysis_version,candidate_count
                FROM comparison_session ORDER BY created_at DESC,session_id LIMIT 100""").fetchall()
        return [dict(row) for row in rows]
