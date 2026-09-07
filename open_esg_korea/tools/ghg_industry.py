"""ghg_industry — 지정업종별 온실가스 배출량 순위와 업종 안 법인 순위(GIR 명세서)."""

from __future__ import annotations

from open_esg_korea.services.contracts import as_pretty_json
from open_esg_korea.services.ghg import build_ghg_industry_payload
from open_esg_korea.tools._shared import dash, footer, head, num


def _render(payload: dict) -> str:
    d = payload["data"]
    if payload["status"] == "no_data":
        lines = head(f"업종별 온실가스 ({d.get('year', '')})", payload)
        if d.get("industry_candidates"):
            lines += ["혹시 이 업종인가요?", ""] + [f"- {c}" for c in d["industry_candidates"]]
        return "\n".join(lines + footer(payload))
    if "companies" in d:
        lines = head(f"{' · '.join(d['matched_industries'])} 온실가스 배출량 ({d['year']})", payload)
        lines += [f"업종 합계 {num(d['industry_emissions_tco2eq'])} tCO₂eq — 전체 명세서의 {dash(d['industry_share_pct'])}% · "
                  f"법인 {d['companies_total']}개 (상위 {len(d['companies'])})", "",
                  "| 순위 | 법인명 | 지정구분 | 배출량(tCO₂eq) | 업종 내 비중 | 에너지(TJ) |", "|---|---|---|---|---|---|"]
        for r in d["companies"]:
            lines.append(f"| {r['rank']} | {r['name']} | {r['designation']} | **{num(r['emissions_tco2eq'])}** | "
                         f"{dash(r['share_in_industry_pct'])}% | {num(r['energy_tj'])} |")
    else:
        lines = head(f"업종별 온실가스 배출량 ({d['year']})", payload)
        lines += [f"명세서 제출 법인 {d['total_reporting_entities']:,}개 · 합계 {num(d['total_emissions_tco2eq'])} tCO₂eq · "
                  f"업종 {d['industries_total']}개 (상위 {len(d['industries'])})", "",
                  "| 순위 | 지정업종 | 법인 수 | 배출량(tCO₂eq) | 비중 | 에너지(TJ) |", "|---|---|---|---|---|---|"]
        for i, g in enumerate(d["industries"], 1):
            lines.append(f"| {i} | {g['industry']} | {g['companies']} | **{num(g['emissions_tco2eq'])}** | "
                         f"{dash(g['share_pct'])}% | {num(g['energy_tj'])} |")
    lines += ["", "> 명세서 기준(규제 대상 업체만, 직접+간접). 업종은 GIR 지정업종(목표관리)/계획업종(할당) 표기다."]
    lines += footer(payload)
    return "\n".join(lines)


def register_tools(mcp):

    @mcp.tool()
    async def ghg_industry(industry: str = "", year: int | None = None, top: int = 20, format: str = "md") -> str:
        """desc: 업종별 온실가스 — industry 를 비우면 지정업종별 배출량 순위(법인 수·비중), 주면 그 업종 안 법인 순위와 업종 내 비중. GIR 명세서 합산.
        when: "철강 업종 배출량 순위", "반도체 회사들 탄소배출 비교", "어느 업종이 가장 많이 배출하나", "○○는 업종에서 몇 위".
        rule: 명세서 대상 업체만 합산한다(규제 기준). 업종명은 부분일치(「철강」→「1차 철강 제조업」). 국가 전체 통계는 ghg_national_inventory 를 쓴다.
        params: industry(업종명 부분, 선택), year(YYYY, 선택), top(상위 몇 개, 기본 20), format(md|json)
        ref: ghg_emissions, ghg_national_inventory, esg_screener
        """
        payload = await build_ghg_industry_payload(industry, year, top=top)
        return as_pretty_json(payload) if format == "json" else _render(payload)
