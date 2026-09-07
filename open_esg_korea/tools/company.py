"""company — 회사 식별. 모든 도구의 공통 입구."""

from __future__ import annotations

from open_esg_korea.krx.client import get_client
from open_esg_korea.services.company import resolve_company
from open_esg_korea.services.contracts import AnalysisStatus, ToolEnvelope, as_pretty_json, source_block
from open_esg_korea.tools._shared import candidates_table, footer, head


def register_tools(mcp):

    @mcp.tool()
    async def company(query: str, format: str = "md") -> str:
        """desc: 회사 식별 — 회사명/종목코드 → KRX ESG 포털 종목코드(isu_cd)·약명·ISIN. 모든 ESG 도구의 공통 입구.
        when: 회사명이 애매하거나 후속 도구에 넣을 종목코드를 확정할 때. 확정 후에는 다른 도구에 종목코드를 넘긴다.
        rule: 검색기 색인은 유가증권(KOSPI) 상장사다. 코스닥은 6자리 종목코드로 직접 조회한다. 부분 일치가 하나면 추정 선택하고 그 사실을 밝힌다.
        params: query(회사명 또는 6자리 종목코드), format(md|json)
        ref: esg_ratings, governance_indicators, sustainability_reports
        """
        client = get_client()
        res = await resolve_company(query, client)
        env = ToolEnvelope(tool="company", status=res.status, subject=query, warnings=list(res.warnings),
                           source=source_block("ratings"))
        if res.status is AnalysisStatus.EXACT:
            info = await client.issue_info(res.selected["isu_cd"]) or {}
            env.data = {"company": {**res.selected, "isin": info.get("rep_isu_cd") or None,
                                    "issuer_code": info.get("isur_cd") or None}}
            env.next_actions = [f"esg_ratings(company=\"{res.selected['isu_cd']}\")"]
        else:
            env.data = {"query": query, "candidates": res.candidates}
        payload = env.to_dict()
        if format == "json":
            return as_pretty_json(payload)
        if res.status is not AnalysisStatus.EXACT:
            return candidates_table(payload, "company")
        c = payload["data"]["company"]
        lines = head(f"{c['name']} ({c['isu_cd']})", payload)
        lines += ["| 항목 | 값 |", "|---|---|",
                  f"| 종목코드 | `{c['isu_cd']}` |", f"| ISIN | `{c.get('isin') or '-'}` |",
                  f"| 발행인코드 | `{c.get('issuer_code') or '-'}` |",
                  f"| 포털 색인 | {'유가증권 검색기 등재' if c.get('in_index') else '색인 밖(코드 직접 조회)'} |",
                  f"| 매칭 | {c.get('match', '')} |"]
        lines += footer(payload)
        return "\n".join(lines)
