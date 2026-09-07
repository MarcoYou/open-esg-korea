"""ghg_emissions — 회사별 온실가스 배출량(GIR 명세서) + 배출권거래제 할당/인증."""

from __future__ import annotations

from open_esg_korea.services.contracts import as_pretty_json
from open_esg_korea.services.ghg import build_ghg_emissions_payload
from open_esg_korea.tools._shared import candidates_table, dash, footer, head, num


def _render(payload: dict) -> str:
    d = payload["data"]
    c = d["company"]
    lines = head(f"{c['name']} 온실가스 배출량 ({d['year']})", payload)
    if d["statement"]:
        lines += ["| 법인명 | 지정구분 | 지정업종 | 배출량(tCO₂eq) | 에너지(TJ) | 검증기관 |", "|---|---|---|---|---|---|"]
        for r in d["statement"]:
            lines.append(f"| {r['name']} | {r['designation']} | {r['industry']} | **{num(r['emissions_tco2eq'])}** | "
                         f"{num(r['energy_tj'])} | {r['verifier']} |")
    if d.get("related_entities"):
        lines += ["", "## 관련 법인(이름이 겹치는 행)", "| 법인명 | 지정구분 | 지정업종 | 배출량(tCO₂eq) |", "|---|---|---|---|"]
        for r in d["related_entities"]:
            lines.append(f"| {r['name']} | {r['designation']} | {r['industry']} | {num(r['emissions_tco2eq'])} |")
    if any(h["emissions_tco2eq"] is not None for h in d["history"]):
        lines += ["", "## 추이", "| 연도 | 배출량(tCO₂eq) | 전년비 | 에너지(TJ) |", "|---|---|---|---|"]
        for h in d["history"]:
            yoy = h.get("yoy_pct")
            lines.append(f"| {h['year']} | {num(h['emissions_tco2eq'])} | {dash(f'{yoy:+.1f}%' if yoy is not None else None)} | "
                         f"{num(h['energy_tj'])} |")
    ets = d["ets"]
    if ets["by_year"]:
        lines += ["", "## 배출권거래제(ETS) 할당 대비 인증 배출량", "| 이행연도 | 부문 | 할당량(t) | 인증 배출량(t) | 잉여(+)/부족(−) |",
                  "|---|---|---|---|---|"]
        for e in ets["by_year"]:
            s = e["surplus_t"]
            lines.append(f"| {e['year']} | {dash(e['sector'])} | {num(e['allocation_t'])} | {num(e['certified_t'])} | "
                         f"{dash(f'{s:+,}' if s is not None else None)} |")
    for p in ets["pre_allocation"]:
        vals = " · ".join(f"{y} {num(v)}" for y, v in p["allocation_by_year_t"].items())
        lines += ["", f"- {p['period']}차 계획기간({p['years']}) 사전할당량(t, 유상 {dash(p['paid_allocation'])}): {vals}"]
    lines += ["", "> " + " ".join(d.get("reading_notes", []))]
    lines += footer(payload)
    return "\n".join(lines)


def register_tools(mcp):

    @mcp.tool()
    async def ghg_emissions(company: str, year: int | None = None, format: str = "md") -> str:
        """desc: 회사별 온실가스 배출량 — GIR 명세서(검증된 규제 기준 tCO₂eq·에너지 TJ·지정업종·검증기관) + 5년 추이 + 배출권거래제 할당량 대비 인증 배출량·사전할당량.
        when: "○○ 탄소배출량", "온실가스 얼마나 배출", "배출권 할당 대비 얼마나 썼나", "배출량 줄고 있나".
        rule: 대상 업체(연 1,170개 안팎)만 있다 — 없으면 no_data 이지 0 이 아니다. 자회사가 따로 지정되면 「관련 법인」에 나온다. 지정구분 「사업장」은 그 사업장만이다. 보고서의 Scope 1·2·3 수치와 다른 기준이다. year 를 비우면 자료가 있는 최신 해.
        params: company(회사명|6자리 종목코드), year(YYYY, 선택 — 2011~), format(md|json)
        ref: ghg_industry, ghg_national_inventory, sustainability_reports, esg_ratings
        """
        payload = await build_ghg_emissions_payload(company, year)
        if format == "json":
            return as_pretty_json(payload)
        if payload["status"] in ("ambiguous", "error"):
            return candidates_table(payload, "ghg_emissions")
        return _render(payload)
