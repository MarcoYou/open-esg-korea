"""회사 하나의 **연도별 ESG 수치** — 최근 보고서 여러 건의 부록 표를 행끼리 이어 붙이고, GIR 명세서를 옆에 둔다.

**물어볼 때 만든다(2026-09-24 결정).** 미리 뽑아 저장하지 않는다 — 질문이 오면 최근 보고서 N건을 받아 부록 표를 풀고
(`report_text.load_document` 가 데이터 장을 풀어 메모리에 24시간 둔다), 그 자리에서 잇는다. 저장소·DB 에 남기지 않는다.

잇는 규칙 — 값을 고르거나 섞지 않는다:
  - **같은 행**은 행 이름·상위 행·단위·경계(열 머리에서 연도를 뺀 나머지 — 국내/해외, DX/DS, 회사명, 목표)가 모두 같을
    때뿐이다(공백·각주 표지는 무시). 이름이 조금 달라도(「사업장 에너지 사용량」↔「에너지 사용량」) 잇지 않는다 — 틀리게
    잇느니 두 줄로 둔다.
  - 한 해 값이 여러 보고서에 나오면 **최신 보고서 값**을 보여 주고, 앞 보고서와 다르면 「수정됨」으로 표시하며 이전 값도
    함께 싣는다. 회사가 다시 낸 값을 따르는 것이지 평균·선택이 아니다.
  - 검사를 통과한 행(`ok`)만 잇는다. 걸린 행은 각 보고서의 `sustainability_report_data` 에서 원문 줄로 본다.
  - GIR 명세서(국내 규제 기준 배출량·에너지)는 **따로** 싣는다 — 보고서 행과 경계가 달라 한 줄로 합치지 않는다(규칙 8).
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from typing import Any

from open_esg_korea.krx import codes
from open_esg_korea.krx.client import KrxEsgClient
from open_esg_korea.krx.kind import KindClient
from open_esg_korea.services.contracts import AnalysisStatus, ToolEnvelope
from open_esg_korea.services.ghg import build_ghg_emissions_payload
from open_esg_korea.services.report_text import open_report
from open_esg_korea.services.reports import build_sustainability_reports_payload

#: 읽을 최근 보고서 수. 보고서 한 건이 3~5개 연도를 싣고 해마다 겹치므로 3건이면 대개 5~6개 연도가 된다.
DEFAULT_REPORTS = 3
MAX_REPORTS = 5

_MARKS_RE = re.compile(r"\d{1,2}\)|[¹²³⁴⁵⁶⁷⁸⁹⁰*※]+")


def _norm(text: str) -> str:
    return re.sub(r"\s+", "", _MARKS_RE.sub("", text or "")).lower()


def _number(text: str) -> float | None:
    t = text.replace(",", "").replace("%", "").strip()
    if t.startswith("(") and t.endswith(")"):
        t = "-" + t[1:-1]
    try:
        return float(t.replace("−", "-"))
    except ValueError:
        return None


def _same_value(a: str, b: str) -> bool:
    na, nb = _number(a), _number(b)
    if na is None or nb is None:
        return a.strip() == b.strip()
    return abs(na - nb) <= 1e-9 * max(1.0, abs(na), abs(nb))


@dataclass
class Point:
    value: str
    report_year: str
    acpt_no: str
    page: int
    table: str


@dataclass
class Series:
    parent: str
    label: str
    unit: str
    boundary: str
    points: dict[str, list[Point]] = field(default_factory=dict)       # 데이터 연도 → 보고서별 값(최신 보고서 먼저)
    order: tuple[int, int] = (0, 0)                                    # 최신 보고서 안의 (쪽, 행 순서) — 보여 주는 순서
    ambiguous: bool = False                                            # 한 보고서 안에 같은 이름 행이 여럿 — 잇지 않은 줄

    def latest(self, year: str) -> Point:
        return self.points[year][0]

    def restated(self, year: str) -> bool:
        pts = self.points[year]
        return any(not _same_value(p.value, pts[0].value) for p in pts[1:])


def stitch(reports: list[dict[str, Any]]) -> list[Series]:
    """보고서별 표(`Table.to_dict()` 목록)를 최신 보고서부터 받아 행끼리 잇는다. 순수 함수."""
    series: dict[tuple, Series] = {}
    for rank, rep in enumerate(reports):
        # 한 보고서 안에서 같은 이름(상위 행·행·단위·경계)이 여러 번 나오면 서로 다른 행이다(사업장별 표에서 「공업용수」가
        # 사업장마다 — LG에너지솔루션 2024). 이런 행은 다른 해 보고서와 잇지 않고 그 보고서 안에서 따로 둔다.
        seen: dict[tuple, int] = {}
        for t in rep["tables"]:
            years_ = {c["key"]: (c["year"], [p for p in c["path"] if p != c["year"]]) for c in t["columns"]}
            for r in t["rows"]:
                if r["status"] != "ok":
                    continue
                for key in r["values"]:
                    year, rest = years_.get(key, (None, []))
                    if year:
                        base = (_norm(r.get("parent", "")), _norm(r["label"]), _norm(r["unit"]), _norm("·".join(rest)))
                        seen[base + (year,)] = seen.get(base + (year,), 0) + 1
        duplicated = {k[:4] for k, c in seen.items() if c > 1}
        n = 0
        for t in rep["tables"]:
            years = {c["key"]: (c["year"], [p for p in c["path"] if p != c["year"]]) for c in t["columns"]}
            for r in t["rows"]:
                n += 1
                if r["status"] != "ok":
                    continue
                for key, value in r["values"].items():
                    year, rest = years.get(key, (None, []))
                    if not year:
                        continue
                    boundary = "·".join(rest)
                    sk: tuple = (_norm(r.get("parent", "")), _norm(r["label"]), _norm(r["unit"]), _norm(boundary))
                    if sk in duplicated:
                        sk = sk + (rep["year"], t["page"], n)          # 그 보고서 안의 그 행으로만
                    s = series.get(sk)
                    if s is None:
                        s = series[sk] = Series(parent=r.get("parent", ""), label=r["label"], unit=r["unit"],
                                                boundary=boundary, order=(rank, t["page"] * 10_000 + n),
                                                ambiguous=len(sk) > 4)
                    s.points.setdefault(year, []).append(
                        Point(value=value, report_year=str(rep["year"]), acpt_no=rep.get("acpt_no") or "",
                              page=t["page"], table=t["title"]))
    return sorted(series.values(), key=lambda s: s.order)


def _matches(needle: str, s: Series) -> bool:
    return any(needle in _norm(x) for x in (s.label, s.parent, s.boundary)) or \
        any(needle in _norm(p.table) for pts in s.points.values() for p in pts)


async def _read_report(company: str, year: str, client: KrxEsgClient | None,
                       kind: KindClient | None) -> dict[str, Any]:
    opened = await open_report("esg_timeseries", company, year=int(year), client=client, kind=kind, out={})
    rep = {"year": year, "acpt_no": (opened.out.get("report") or {}).get("acpt_no"),
           "title": (opened.out.get("report") or {}).get("report_title"),
           "pdf": (opened.out.get("attachment") or {}).get("url"), "tables": [], "problem": ""}
    if opened.doc is None:
        rep["problem"] = "; ".join(opened.env.warnings[-1:]) or "보고서를 열지 못했습니다"
        return rep
    doc = opened.doc
    if not doc.section:
        rep["problem"] = "데이터 장을 찾지 못했습니다(본문에 흩어진 표이거나 데이터북 별도 발간)"
        return rep
    rep["data_section"] = [doc.section[0], doc.section[-1]]
    rep["tables"] = [t.to_dict() for p in doc.section for t in doc.tables.get(p, [])]
    return rep


async def build_esg_timeseries_payload(company: str, *, find: str = "", reports: int = DEFAULT_REPORTS,
                                       client: KrxEsgClient | None = None,
                                       kind: KindClient | None = None) -> dict[str, Any]:
    reports = max(1, min(MAX_REPORTS, int(reports or DEFAULT_REPORTS)))
    base = await build_sustainability_reports_payload(company, client=client, kind=kind)
    env = ToolEnvelope(tool="esg_timeseries", status=base["status"], subject=company,
                       warnings=list(base["warnings"]), source=base["source"], license=codes.KIND_LICENSE_NOTICE)
    if base["status"] != AnalysisStatus.EXACT.value:
        env.data = base["data"]
        return env.to_dict()
    listed = [r for r in base["data"].get("reports") or [] if r.get("year")]
    years = sorted({r["year"] for r in listed}, reverse=True)[:reports]
    read = await asyncio.gather(*(_read_report(company, y, client, kind) for y in years))
    usable = [r for r in read if r["tables"]]
    for r in read:
        if r["problem"]:
            env.warnings.append(f"{r['year']}년 보고서는 잇지 못했습니다 — {r['problem']}.")

    all_series = stitch(usable)
    needle = _norm(find)
    shown = [s for s in all_series if _matches(needle, s)] if needle else all_series
    if needle and not shown:
        env.warnings.append(f"「{find}」가 들어간 행을 찾지 못했습니다(행 이름·상위 행·경계·표 제목에서, 공백 무시). "
                            "표기가 다를 수 있습니다 — 「없다」고 단정하지 마세요.")

    gir = await build_ghg_emissions_payload(company, history_years=7, client=client)
    gir_block = {"status": gir["status"], "history": (gir.get("data") or {}).get("history") or [],
                 "note": "GIR 명세서 — 국내 배출권거래제·목표관리제 대상의 검증된 규제 기준(직접+간접). 보고서 행과 경계가 달라 "
                         "한 줄로 합치지 않는다. 명세서 대상이 아니면 비어 있고, 배출량이 0 이라는 뜻이 아니다."}

    data_years = sorted({y for s in shown for y in s.points})
    restated = [(s, y) for s in shown for y in sorted(s.points) if s.restated(y)]
    env.data = {
        "company": base["data"].get("company"), "find": find,
        "reports": [{k: r.get(k) for k in ("year", "acpt_no", "title", "pdf", "data_section", "problem")} for r in read],
        "years": data_years,
        "series": [_series_dict(s) for s in shown],
        "counts": {"series": len(shown), "all_series": len(all_series), "restated_points": len(restated),
                   "reports_used": len(usable)},
        "gir": gir_block,
    }
    env.warnings += [
        "보고서 여러 건의 부록 표를 **물어본 지금** 받아 이었습니다 — 저장해 둔 데이터가 아닙니다(값마다 보고서·쪽·접수번호).",
        "행은 이름·상위 행·단위·경계가 모두 같을 때만 이었습니다. 이름이 조금 달라진 해는 다른 줄로 나옵니다.",
        "한 해 값이 여러 보고서에 있으면 최신 보고서 값을 보이고, 앞 보고서와 다르면 「수정됨」(✎)으로 표시했습니다.",
    ]
    if not usable:
        env.status = AnalysisStatus.NO_DATA
        env.warnings.append("부록 표를 푼 보고서가 없습니다 — sustainability_report_text 로 원문을 보세요.")
    env.next_actions = [
        f'sustainability_report_data(company="{company}", year=…) — 한 해 보고서의 표(검사에 걸린 행 포함)',
        f'ghg_emissions(company="{company}") — GIR 명세서·배출권 할당',
    ]
    return env.to_dict()


def _series_dict(s: Series) -> dict[str, Any]:
    return {
        "parent": s.parent, "label": s.label, "unit": s.unit, "boundary": s.boundary, "not_stitched": s.ambiguous,
        "values": {y: s.latest(y).value for y in sorted(s.points)},
        "restated": {y: [{"value": p.value, "report_year": p.report_year} for p in s.points[y]]
                     for y in sorted(s.points) if s.restated(y)},
        "sources": {y: {"report_year": s.latest(y).report_year, "acpt_no": s.latest(y).acpt_no,
                        "page": s.latest(y).page, "table": s.latest(y).table} for y in sorted(s.points)},
    }
