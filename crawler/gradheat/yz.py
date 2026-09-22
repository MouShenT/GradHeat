"""研招网（yz.chsi.com.cn）解析器。

数据源核实（2026-09-18 实测）：
  ✅ /sch/search.do?ylgx=1    双一流院校列表，服务端渲染，分页 start=N，每页 20
  ✅ /sch/schoolInfo--schId-*.dhtml   院校详情，服务端渲染
  ❌ /zsml/a/dw.do            专业目录接口，302 → 学信网登录，**需登录**
"""

from __future__ import annotations

import re

from lxml import html as lxml_html

BASE = "https://yz.chsi.com.cn"

# 院校特性标签
TAG_985 = "985"
TAG_211 = "211"
TAG_SYL = "双一流"


def _text(el) -> str:
    return re.sub(r"\s+", " ", el.text_content()).strip() if el is not None else ""


def parse_school_list(page_html: str, *, source_url: str) -> list[dict]:
    """解析 /sch/search.do 的院校列表页。"""
    doc = lxml_html.fromstring(page_html)
    out: list[dict] = []

    for item in doc.cssselect("div.sch-item"):
        link = item.cssselect("a.js-yxk-yxmc")
        if not link:
            continue
        a = link[0]
        name = _text(a)
        href = a.get("href") or ""
        m = re.search(r"schId-(\d+)", href)
        if not name or not m:
            continue

        tags = [_text(t) for t in item.cssselect("span.sch-tag")]

        # sch-department: 地区 / 主管部门：X / 研究生院 / 自划线（后两者可选）
        dept_text = _text(item.cssselect("div.sch-department")[0]) if item.cssselect(
            "div.sch-department"
        ) else ""
        area = ""
        authority = ""
        has_grad_school = "研究生院" in dept_text
        is_self_line = "自划线" in dept_text
        if dept_text:
            # 去掉图标遗留字符与标签词，剩余按分隔理解
            cleaned = dept_text.replace("研究生院", "").replace("自划线", "").strip()
            m2 = re.search(r"主管部门[:：]\s*([^ ]+)", cleaned)
            if m2:
                authority = m2.group(1).strip()
                area = cleaned[: m2.start()].strip()
            else:
                area = cleaned

        # 招生公告链接里带 dwdm（单位代码）与 ssdm（省市代码）
        dwdm = ssdm = None
        for a2 in item.cssselect("a"):
            href2 = a2.get("href") or ""
            m3 = re.search(r"dwdm=(\d+)", href2)
            if m3:
                dwdm = m3.group(1)
                m4 = re.search(r"ssdm=(\d+)", href2)
                ssdm = m4.group(1) if m4 else None

        out.append(
            {
                "sch_id": m.group(1),
                "name": name,
                "tags": tags,
                "is_985": any(TAG_985 in t for t in tags),
                "is_211": any(TAG_211 in t for t in tags),
                "is_syl": any(TAG_SYL in t for t in tags),
                "area": area,
                "authority": authority,
                "has_grad_school": has_grad_school,
                "is_self_line": is_self_line,
                "dwdm": dwdm,
                "ssdm": ssdm,
                "detail_url": BASE + href,
                "source_url": source_url,
                "source_level": "L1",  # 研招网 = 官方
            }
        )

    return out


def max_start(page_html: str) -> int:
    """从分页条推断最大 start 偏移。"""
    starts = [int(x) for x in re.findall(r"ylgx=1&start=(\d+)", page_html)]
    return max(starts) if starts else 0