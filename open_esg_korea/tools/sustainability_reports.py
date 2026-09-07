"""sustainability_reports — 지속가능경영보고서 목록·작성기준·검증기관."""

from __future__ import annotations

from open_esg_korea.services.contracts import as_pretty_json
from open_esg_korea.services.reports import build_sustainability_reports_payload
from open_esg_korea.tools._shared import candidates_table, dash, footer, head


def _render(payload: dict) -> str:
    d = payload["data"]
    c = d["company"]
    s = d["summary"]
    lines = head(f"{c['name']} 지속가능경영보고서", payload)
    lines += [f"- 등록 보고서: {dash(s['report_count'])}건 · 사용 기준: {', '.join(s['standards_ever_used']) or '-'} · "
              f"최근 검증기관: {dash(s['latest_verifier'])}", ""]
    if d["reports"]:
        lines += ["| 연도 | 보고서 | 업종 | 작성기준 | 제3자 검증 | 원문 |", "|---|---|---|---|---|---|"]
        for r in d["reports"]:
            link = f"[KIND]({r['links']['kind']}) · [DART]({r['links']['dart']})" if r["links"] else "-"
            lines.append(f"| {dash(r['year'])} | {dash(r['title'])} | {dash(r['industry'])} | "
                         f"{', '.join(r['standards']) or '-'} | {dash(r['third_party_verifier'])} | {link} |")
    lines += footer(payload)
    return "\n".join(lines)


def register_tools(mcp):

    @mcp.tool()
    async def sustainability_reports(company: str, from_year: int | None = None, to_year: int | None = None,
                                     format: str = "md") -> str:
        """desc: 지속가능경영보고서 목록 — 연도별 보고서, 작성기준(GRI/SASB/TCFD/UN SDGs), 제3자 검증기관, 접수번호와 KIND/DART 원문 링크.
        when: "보고서 냈어?", "GRI 기준 썼나", "검증은 누가", "보고서 원문 링크".
        rule: 목록은 KRX 포털이 거래소 공시(KIND)에서 집계한 것이다. 없다고 나와도 회사가 자사 사이트에만 올렸을 수 있다. 원문 본문은 Phase 2(DART 연동) 전까지 링크만 준다.
        params: company, from_year/to_year(YYYY, 선택), format(md|json)
        ref: company, esg_ratings, esg_disclosures
        """
        payload = await build_sustainability_reports_payload(company, from_year=from_year, to_year=to_year)
        if format == "json":
            return as_pretty_json(payload)
        if payload["status"] in ("ambiguous", "error"):
            return candidates_table(payload, "sustainability_reports")
        return _render(payload)
