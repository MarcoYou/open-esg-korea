"""governance_indicators — 기업지배구조 핵심지표 15개 준수 여부(+비교)."""

from __future__ import annotations

from open_esg_korea.services.contracts import as_pretty_json
from open_esg_korea.services.governance import build_governance_indicators_payload
from open_esg_korea.tools._shared import candidates_table, dash, footer, head, ox


def _render(payload: dict) -> str:
    d = payload["data"]
    c = d["company"]
    lines = head(f"{c['name']} 지배구조 핵심지표 ({d['year']})", payload)
    if payload["status"] == "no_data":
        return "\n".join(lines + footer(payload))
    cmp = d.get("compare")
    lines.append(f"- **준수율 {dash(d['compliance_rate'])}** ({d['complied_count']}/{d['answered_count']} 준수)"
                 + (f" · 비교 {cmp['company']['name']}: {dash(cmp.get('compliance_rate'))}" if cmp else ""))
    lines.append(f"- 기준: {d['basis']}")
    lines.append("")
    if cmp:
        cmap = {i["key"]: i["complied"] for i in cmp.get("indicators", [])}
        lines += [f"| # | 핵심지표 | {c['name']} | {cmp['company']['name']} |", "|---|---|---|---|"]
        for i in d["indicators"]:
            lines.append(f"| {i['no']} | {i['label']} | {ox(i['complied'])} | {ox(cmap.get(i['key']))} |")
    else:
        lines += ["| # | 핵심지표 | 준수 |", "|---|---|---|"]
        for i in d["indicators"]:
            lines.append(f"| {i['no']} | {i['label']} | {ox(i['complied'])} |")
    lines += footer(payload)
    return "\n".join(lines)


def register_tools(mcp):

    @mcp.tool()
    async def governance_indicators(company: str, year: int | None = None, compare: str = "",
                                    format: str = "md") -> str:
        """desc: 기업지배구조보고서 핵심지표 15개 준수 여부(O/X)와 준수율. 비교회사를 주면 나란히 표시.
        when: "전자투표 하나", "집중투표제 채택했나", "사외이사가 이사회 의장인가", "지배구조 준수율", "A사 vs B사 지배구조".
        rule: 값은 회사가 제출한 기업지배구조보고서(정정 포함)를 KRX 가 집계한 것이다. 항목이 없으면 미준수가 아니라 보고서 미제출(의무대상 아님 등)이다. year 를 비우면 올해, 없으면 전년.
        params: company, year(YYYY, 선택), compare(비교회사명|종목코드, 선택), format(md|json)
        ref: company, governance_policies, esg_disclosures
        """
        payload = await build_governance_indicators_payload(company, year, compare=compare)
        if format == "json":
            return as_pretty_json(payload)
        if payload["status"] in ("ambiguous", "error"):
            return candidates_table(payload, "governance_indicators")
        return _render(payload)
