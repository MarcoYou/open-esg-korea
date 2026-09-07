"""esg_disclosures — 기업지배구조보고서 공시 이력."""

from __future__ import annotations

from open_esg_korea.services.contracts import as_pretty_json
from open_esg_korea.services.reports import build_esg_disclosures_payload
from open_esg_korea.tools._shared import candidates_table, dash, footer, head


def _render(payload: dict) -> str:
    d = payload["data"]
    c = d["company"]
    lines = head(f"{c['name']} 지배구조보고서 공시 이력", payload)
    if d["disclosures"]:
        lines += ["| 공시일시 | 제목 | 접수번호 | 원문 |", "|---|---|---|---|"]
        for x in d["disclosures"]:
            link = f"[원문 보기]({x['links']['kind']})" if x["links"] else "-"
            lines.append(f"| {dash(x['disclosed_at'])} | {dash(x['title'])} | `{dash(x['acpt_no'])}` | {link} |")
    lines += footer(payload)
    return "\n".join(lines)


def register_tools(mcp):

    @mcp.tool()
    async def esg_disclosures(company: str, from_date: str = "", to_date: str = "", format: str = "md") -> str:
        """desc: 기업지배구조보고서 공시 이력 — 공시일시·제목·KIND 접수번호·원문 링크(정정 공시 포함).
        when: "지배구조보고서 언제 냈어", "정정 있었나", "원문 링크".
        rule: 목록은 KRX 포털 집계(거래소 공시). 기간을 비우면 2019년부터 전체.
        params: company, from_date/to_date(YYYYMMDD, 선택), format(md|json)
        ref: governance_indicators, sustainability_reports
        """
        payload = await build_esg_disclosures_payload(company, from_date=from_date, to_date=to_date)
        if format == "json":
            return as_pretty_json(payload)
        if payload["status"] in ("ambiguous", "error"):
            return candidates_table(payload, "esg_disclosures")
        return _render(payload)
