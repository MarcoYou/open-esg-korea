"""esg_ratings — 기관별 ESG 등급 + 3년 추이."""

from __future__ import annotations

from open_esg_korea.services.contracts import as_pretty_json
from open_esg_korea.services.esg_ratings import build_esg_ratings_payload
from open_esg_korea.tools._shared import candidates_table, dash, footer, head


def _distribution_lines(d: dict) -> list[str]:
    """「좋은 편인가」 — 같은 기관 안에서 **센 수**로 보여준다. 「상위 N%」를 만들지 않는다."""
    dist = d.get("distribution")
    if not dist or not dist.get("by_agency"):
        return []
    group = dist.get("gics_group")
    title = f"## 같은 기관 안에서의 위치 ({dist.get('year')}년 · 유가증권 {dist.get('universe')}사)"
    lines = ["", title,
             "| 기관 | 이 회사 | 평가 대상 | 이 등급 이상 | 동점 | 산업군 안 |", "|---|---|---|---|---|---|"]
    for ctx in dist["by_agency"].values():
        mine = ctx["score"] if ctx["kind"] == "score" else ctx["grade"]
        cover = f"{ctx['rated']}사" + (f" ({ctx['coverage_pct']}%)" if ctx.get("coverage_pct") else "")
        above = f"{ctx['at_or_above']}사"
        if ctx.get("at_or_above_pct") is not None:
            above += f" ({ctx['at_or_above_pct']}%)"
        peer = ctx.get("peer_group")
        peer_cell = (f"{peer['at_or_above']}/{peer['rated']}사"
                     + (f" ({peer['at_or_above_pct']}%)" if peer.get("at_or_above_pct") is not None else "")
                     ) if peer else "-"
        lines.append(f"| {ctx['agency']} | **{mine}** | {cover} | {above} | {ctx['same_grade']}사 | {peer_cell} |")
    if group:
        lines.append("")
        lines.append(f"- 산업군(GICS): **{group['group']}** ({group['group_code']}) · {group['sector']} 섹터 "
                     f"· 상장 {group['listed']}사 — 「산업군 안」 열은 이 안에서 센 것이다")
    for ctx in dist["by_agency"].values():
        if ctx.get("counts"):
            spread = " · ".join(f"{g} {n}" for g, n in ctx["counts"].items())
            lines.append("")
            lines.append(f"- {ctx['agency']} 분포: {spread}")
    lines += ["", "> " + " ".join(dist.get("reading_notes", []))]
    return lines


def _render(payload: dict) -> str:
    d = payload["data"]
    c = d["company"]
    lines = head(f"{c['name']} ESG 등급 ({d['year']})", payload)
    lines += ["| 기관 | 스케일 | 연도 | ESG | E | S | G |", "|---|---|---|---|---|---|---|"]
    for r in d["ratings"]:
        lines.append(f"| {r['agency']} | {r['scale']} | {dash(r['year'])} | **{dash(r['esg'])}** | "
                     f"{dash(r['e'])} | {dash(r['s'])} | {dash(r['g'])} |")
    if d.get("kcgs_history"):
        lines += ["", "## KCGS 3년 추이", "| 연도 | KCGS ESG | 매출(억원) | 영업이익(억원) |", "|---|---|---|---|"]
        for h in d["kcgs_history"]:
            lines.append(f"| {dash(h['year'])} | {dash(h['kcgs_esg'])} | {dash(h['sales_100m_krw'])} | "
                         f"{dash(h['operating_income_100m_krw'])} |")
    lines += _distribution_lines(d)
    lines += ["", "> " + " ".join(d.get("reading_notes", []))]
    lines += footer(payload)
    return "\n".join(lines)


def register_tools(mcp):

    @mcp.tool()
    async def esg_ratings(company: str, year: int | None = None, format: str = "md") -> str:
        """desc: 기관별 ESG 등급표 — KCGS·MSCI·한국ESG연구소·S&P·서스틴베스트의 ESG/E/S/G 등급(연도별) + KCGS 3년 추이와 매출·영업이익.
        when: "○○ ESG 등급 어때", "MSCI 등급", "KCGS 환경 등급", "작년보다 올랐나".
        rule: 기관마다 스케일이 다르다 — 기관 간 등급을 나란히 비교하지 않는다. S&P 는 0-100 점수. `-` 는 미평가(null)이며 나쁜 등급이 아니다. year 를 비우면 올해, 없으면 전년으로 물러선다. 「좋은 편인가」는 **같은 기관 안의 분포**로 답한다 — 「상위 N%」를 만들지 않는다(등급이 6~7단계라 동점이 30~60%다). 분모는 그 기관이 평가한 회사 수이고, 기관마다 평가 대상이 다르다(MSCI 는 795사 중 74사뿐).
        params: company(회사명|6자리 종목코드), year(YYYY, 선택), format(md|json)
        ref: company, governance_indicators, sustainability_reports, esg_screener
        """
        payload = await build_esg_ratings_payload(company, year)
        if format == "json":
            return as_pretty_json(payload)
        if payload["status"] in ("ambiguous", "error"):
            return candidates_table(payload, "esg_ratings")
        return _render(payload)
