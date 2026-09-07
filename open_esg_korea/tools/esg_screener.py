"""esg_screener — 전체 상장사 등급 스크리너."""

from __future__ import annotations

from open_esg_korea.services.contracts import as_pretty_json
from open_esg_korea.services.screener import build_screener_payload
from open_esg_korea.tools._shared import dash, footer, head


def _render(payload: dict) -> str:
    d = payload["data"]
    f = {k: v for k, v in d["filters"].items() if v not in (None, False, "")}
    lines = head(f"ESG 스크리너 ({d['year']})", payload)
    lines.append(f"- 조건: {f or '없음'} · 모집단 {d['universe_count']}사 → **{d['matched_count']}사**"
                 + (" (일부만 표시)" if d["truncated"] else ""))
    lines.append("> " + " ".join(d["reading_notes"]))
    lines += ["", "| 종목코드 | 회사 | KCGS | (E/S/G) | 한국ESG연구소 | MSCI | S&P | 서스틴베스트 | 지속가능보고서 |",
              "|---|---|---|---|---|---|---|---|---|"]
    for c in d["companies"]:
        r = c["ratings"]
        k = r["kcgs"]
        lines.append(f"| `{c['isu_cd']}` | {c['name']} | {dash(k['esg'])} | {dash(k.get('e'))}/{dash(k.get('s'))}/{dash(k.get('g'))} | "
                     f"{dash(r['kesg']['esg'])} | {dash(r['msci']['esg'])} | {dash(r['sp']['esg'])} | "
                     f"{dash(r['sustinvest']['esg'])} | {'Y' if c['has_sustainability_report'] else '-'} |")
    lines += footer(payload)
    return "\n".join(lines)


def register_tools(mcp):

    @mcp.tool()
    async def esg_screener(year: int | None = None, min_kcgs: str = "", min_msci: str = "", min_kesg: str = "",
                           min_sustinvest: str = "", min_sp_score: int | None = None, industry: str = "",
                           require_sustainability_report: bool = False, limit: int = 50,
                           format: str = "md") -> str:
        """desc: 전체 유가증권 상장사 ESG 등급 스크리너 — 기관별 최소 등급·S&P 최소 점수·업종·보고서 제출 여부로 거른다.
        when: "KCGS A 이상 기업", "MSCI AA 이상인 전기·전자 업종", "지속가능경영보고서 낸 화학 기업", "S&P 50점 넘는 회사".
        rule: 모집단은 포털 목록(유가증권만, 2025년 795사). 「이상」은 기관별 서열 안에서만 비교한다(KCGS S>A+>A>B+>B>C>D, MSCI AAA>AA>A>BBB>BB>B>CCC, 서스틴베스트 AA>A>BB>B>C>D>E). 결과는 limit 까지만 싣고 truncated 를 표시한다.
        params: year(YYYY), min_kcgs, min_msci, min_kesg, min_sustinvest(등급 문자열), min_sp_score(0-100), industry(포털 업종명 또는 코드, 예 전기·전자|3015), require_sustainability_report, limit(기본 50), format(md|json)
        ref: esg_ratings, company
        """
        payload = await build_screener_payload(year=year, min_kcgs=min_kcgs, min_msci=min_msci, min_kesg=min_kesg,
                                               min_sustinvest=min_sustinvest, min_sp_score=min_sp_score,
                                               industry=industry, require_sustainability_report=require_sustainability_report,
                                               limit=max(1, min(limit, 300)))
        if format == "json":
            return as_pretty_json(payload)
        return _render(payload)
