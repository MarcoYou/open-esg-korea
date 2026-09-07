"""governance_policies — 지배구조 관련 정책 채택 등 74개 항목."""

from __future__ import annotations

from open_esg_korea.services.contracts import as_pretty_json
from open_esg_korea.services.governance import build_governance_policies_payload
from open_esg_korea.tools._shared import candidates_table, footer, head, ox


def _render(payload: dict) -> str:
    d = payload["data"]
    c = d["company"]
    lines = head(f"{c['name']} 지배구조 정책 채택 현황 ({d['year']})", payload)
    if payload["status"] == "no_data":
        return "\n".join(lines + footer(payload))
    lines.append(f"- 채택 O: {d['adopted_count']}개 (사실 확인 항목 제외) · > " + " ".join(d["reading_notes"]))
    lines += ["", "| # | 항목 | 시행 |", "|---|---|---|"]
    for i in d["policies"]:
        lines.append(f"| {i['no']} | {i['label']}{' *(사실 항목)*' if i['fact_item'] else ''} | "
                     f"{ox(i['adopted'], neutral=i['fact_item'])} |")
    lines += footer(payload)
    return "\n".join(lines)


def register_tools(mcp):

    @mcp.tool()
    async def governance_policies(company: str, year: int | None = None, format: str = "md") -> str:
        """desc: 기업지배구조보고서의 정책 채택·시행 여부 74개 항목(O/X) — 주주제안 절차, 주주환원정책, CEO 승계, ESG 위원회, 사외이사 제도, 감사기구, 밸류업 공시 등.
        when: 핵심지표 15개보다 세부 항목이 필요할 때. "ESG 위원회 있나", "선임사외이사 제도", "밸류업 계획 공시했나", "임원배상책임보험".
        rule: O 개수는 점수가 아니다. `fact_item` 항목(불성실공시법인 지정, 주주제안 제출, 소유구조 변동 등)은 사실 여부라 O 가 나쁜 쪽일 수 있다. 항목별로 읽는다.
        params: company, year(YYYY, 선택), format(md|json)
        ref: governance_indicators, company
        """
        payload = await build_governance_policies_payload(company, year)
        if format == "json":
            return as_pretty_json(payload)
        if payload["status"] in ("ambiguous", "error"):
            return candidates_table(payload, "governance_policies")
        return _render(payload)
