"""esg_timeseries — 회사 하나의 연도별 ESG 수치(보고서 여러 건 부록 표 잇기 + GIR)."""

from __future__ import annotations

import csv
import io

from open_esg_korea.services.contracts import as_pretty_json
from open_esg_korea.services.esg_timeseries import DEFAULT_REPORTS, build_esg_timeseries_payload
from open_esg_korea.tools._shared import candidates_table, footer, head

#: md 로 보여줄 줄(series) 상한 — 넘으면 find 로 좁히거나 csv 로 받으라고 말한다.
_MAX_MD_SERIES = 150
_MAX_MD_YEARS = 8


def _cell(text: str) -> str:
    return str(text).replace("|", r"\|").replace("\n", " ")


def _name(s: dict) -> str:
    return f"{s['parent']} › {s['label']}" if s.get("parent") else s["label"]


def _render(payload: dict) -> str:
    d = payload["data"]
    name = (d.get("company") or {}).get("name", payload.get("subject", ""))
    lines = head(f"{name} 연도별 ESG 수치", payload)
    for r in d.get("reports") or []:
        lines.append(f"- {r['year']}년 보고서: {r.get('title') or '-'}"
                     + (f" · 데이터 장 {r['data_section'][0]}–{r['data_section'][1]}쪽" if r.get("data_section") else "")
                     + (f" · 접수번호 {r['acpt_no']}" if r.get("acpt_no") else "")
                     + (f" — **잇지 못함**: {r['problem']}" if r.get("problem") else ""))
    c = d.get("counts") or {}
    lines.append(f"- 줄 {c.get('series', 0)}개" + (f"(전체 {c.get('all_series', 0)}개 중 「{d['find']}」)" if d.get("find") else "")
                 + f" · 수정된 값 {c.get('restated_points', 0)}개 · 보고서 {c.get('reports_used', 0)}건을 이음")

    series = d.get("series") or []
    years = (d.get("years") or [])[-_MAX_MD_YEARS:]
    if series:
        lines += ["", "## 보고서 부록 (최신 보고서 값, ✎ = 앞 보고서와 다름, ⁂ = 한 보고서에 같은 이름 행이 여럿이라 잇지 않음)", "",
                  "| 행 | 단위 | 경계 | " + " | ".join(years) + " |",
                  "|---|---|---|" + "---:|" * len(years)]
        for s in series[:_MAX_MD_SERIES]:
            cells = [_cell(s["values"].get(y, "")) + (" ✎" if y in s.get("restated", {}) else "") for y in years]
            flag = " ⁂" if s.get("not_stitched") else ""
            lines.append(f"| {_cell(_name(s))}{flag} | {_cell(s['unit'])} | {_cell(s['boundary'])} | " + " | ".join(cells) + " |")
        if len(series) > _MAX_MD_SERIES:
            lines.append(f"\n_줄이 많아 {_MAX_MD_SERIES}개에서 줄였습니다 — `find`(예: 「에너지」「용수」「여성」)로 좁히거나 "
                         "`format=\"csv\"`로 받으세요._")
        notes = [(s, y, pts) for s in series[:_MAX_MD_SERIES] for y, pts in (s.get("restated") or {}).items()]
        if notes:
            lines += ["", "**수정된 값** — 같은 해를 보고서마다 다르게 적었습니다:"]
            for s, y, pts in notes[:30]:
                lines.append(f"- {_cell(_name(s))}"
                             + (f"({_cell(s['boundary'])})" if s["boundary"] else "") + f" {y}년: "
                             + " → ".join(f"{p['value']}({p['report_year']}년 보고서)" for p in reversed(pts)))
    gir = d.get("gir") or {}
    hist = [h for h in gir.get("history") or [] if h.get("emissions_tco2eq") is not None]
    lines += ["", "## GIR 명세서 (국내 규제 기준 — 보고서 행과 따로)", ""]
    if hist:
        lines += ["| 연도 | 배출량(tCO₂eq, 직접+간접) | 에너지(TJ) |", "|---|---:|---:|"]
        lines += [f"| {h['year']} | {h['emissions_tco2eq']:,.0f} | "
                  + (f"{h['energy_tj']:,.0f}" if h.get("energy_tj") is not None else "-") + " |" for h in hist]
    else:
        lines.append("명세서 대상 법인으로 찾지 못했습니다 — 배출량이 0 이라는 뜻이 아닙니다(대상 기준 미만이거나 이름이 다름).")
    lines.append(f"\n_{gir.get('note', '')}_")
    return "\n".join(lines + footer(payload))


CSV_COLUMNS = ["회사", "종목코드", "출처", "상위행", "행", "단위", "경계", "연도", "값", "보고서연도", "공시접수번호", "쪽", "표",
               "최신보고서값", "수정됨"]


def _csv(payload: dict) -> str:
    """긴 형식 — 한 줄에 값 하나. 같은 해를 여러 보고서가 적었으면 보고서마다 한 줄(최신보고서값=Y 인 줄이 표에 보인 값)."""
    d = payload["data"]
    comp = d.get("company") or {}
    base = [comp.get("name", ""), comp.get("isu_cd", "")]
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(CSV_COLUMNS)
    for s in d.get("series") or []:
        for y in sorted(s["values"]):
            src = s["sources"][y]
            restated = y in (s.get("restated") or {})
            w.writerow(base + ["보고서", s["parent"], s["label"], s["unit"], s["boundary"], y, s["values"][y],
                               src["report_year"], src["acpt_no"], src["page"], src["table"], "Y", "Y" if restated else ""])
            for p in (s.get("restated") or {}).get(y, [])[1:]:
                w.writerow(base + ["보고서", s["parent"], s["label"], s["unit"], s["boundary"], y, p["value"],
                                   p["report_year"], "", "", "", "", "Y"])
    for h in (d.get("gir") or {}).get("history") or []:
        if h.get("emissions_tco2eq") is not None:
            w.writerow(base + ["GIR 명세서", "", "온실가스 배출량(직접+간접)", "tCO2eq", "국내 규제 기준", h["year"],
                               h["emissions_tco2eq"], "", "", "", "", "", ""])
            if h.get("energy_tj") is not None:
                w.writerow(base + ["GIR 명세서", "", "에너지 사용량", "TJ", "국내 규제 기준", h["year"],
                                   h["energy_tj"], "", "", "", "", "", ""])
    return buf.getvalue()


def register_tools(mcp):

    @mcp.tool()
    async def esg_timeseries(company: str, find: str = "", reports: int = DEFAULT_REPORTS, format: str = "md") -> str:
        """desc: 회사 하나의 **연도별 ESG 수치** — 최근 지속가능경영보고서 여러 건의 부록 표를 행끼리 이어 붙이고(대개 5~6개 연도), GIR 명세서 배출량·에너지를 옆에 둔다.
        when: "○○ 에너지 사용량 연도별로", "용수 취수량 추이", "여성 임직원 비율 몇 년치", "ESG 데이터 연도별 엑셀로", "과거 값이 수정됐나".
        rule: **물어볼 때 만든다** — 최근 보고서 N건(기본 3)을 받아 부록 표를 풀고 그 자리에서 잇는다. 저장해 둔 데이터가 아니다(메모리 캐시뿐). 행은 이름·상위 행·단위·경계(국내/해외·회사·목표 등)가 모두 같을 때만 잇고, 이름이 조금 다르면 다른 줄로 둔다. 한 해 값이 여러 보고서에 있으면 최신 보고서 값을 보이고 다르면 「수정됨」(✎)과 이전 값을 함께 준다. 검사를 통과한 행만 잇는다. GIR 명세서(국내 규제 기준)는 경계가 달라 보고서 행과 합치지 않고 따로 싣는다. 보고서 여러 건을 받으므로 처음에는 수십 초 걸린다.
        params: company, find(행 이름·상위 행·경계·표 제목에서, 공백 무시 — 예: 「에너지」「용수」「폐기물」「여성」, 선택), reports(읽을 최근 보고서 수 1~5, 기본 3), format(md|csv|json — csv 는 엑셀용 긴 형식)
        ref: sustainability_report_data, ghg_emissions, sustainability_reports
        """
        payload = await build_esg_timeseries_payload(company, find=find, reports=reports)
        if format == "json":
            return as_pretty_json(payload)
        if payload["status"] in ("ambiguous", "error"):
            return candidates_table(payload, "esg_timeseries")
        if format == "csv" and payload["status"] == "exact":
            return _csv(payload)
        return _render(payload)
