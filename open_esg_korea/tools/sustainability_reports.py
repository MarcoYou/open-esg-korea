"""sustainability_reports — 지속가능경영보고서 목록·작성기준·검증기관."""

from __future__ import annotations

from open_esg_korea.services.contracts import as_pretty_json
from open_esg_korea.services.reports import build_sustainability_reports_payload
from open_esg_korea.tools._shared import candidates_table, dash, footer, head


def _detail_lines(d: dict) -> list[str]:
    """최신(또는 지정 연도) 한 건의 자율공시 원문 — 목록이 못 주는 것만 보여준다."""
    det = d.get("detail")
    if not det or det.get("unread"):
        return []
    lines = ["", f"## {dash(det.get('report_title'))} ({dash(det.get('year'))})"]
    verifier = dash(det.get("verifier")).replace(chr(10), " ")
    if det.get("verifier_en"):
        verifier += f" ({det['verifier_en']})"
    lines.append(f"- 검증기관: {verifier} · 제출 확인일 {dash(det.get('confirmed_at'))}")
    if det.get("standards_text"):
        lines.append(f"- 작성기준: {det['standards_text'].replace(chr(10), ' ')}")
    if det.get("publisher_url"):
        lines.append(f"- 회사 공개처: {det['publisher_url']}")
    for att in det.get("attachments") or []:
        lines.append(f"- 첨부 원문: [{att['name']}]({att['url']})")
    if det.get("summary"):
        lines += ["", "**주요내용(공시 원문)**", "", "```", det["summary"], "```"]
    return lines


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
            link = f"[원문 보기]({r['links']['kind']})" if r["links"] else "-"
            # 포털 집계에 아직 없어 KIND 공시에서 찾은 행 — 빈 칸이 「없음」이 아니라 「집계 전」임을 밝힌다.
            year = dash(r["year"]) + (" ⁽ᴷᴵᴺᴰ⁾" if r.get("source") == "kind" else "")
            lines.append(f"| {year} | {dash(r['title'])} | {dash(r['industry'])} | "
                         f"{', '.join(r['standards']) or '-'} | {dash(r['third_party_verifier'])} | {link} |")
        if any(r.get("source") == "kind" for r in d["reports"]):
            lines += ["", "> ⁽ᴷᴵᴺᴰ⁾ 는 포털 집계에 아직 오르지 않아 거래소 공시에서 찾은 건이다 — "
                          "업종·작성기준·검증기관 칸이 빈 것은 「없다」가 아니라 「포털이 아직 집계하지 않았다」는 뜻이고, "
                          "그 값들은 아래 원문에 들어 있다."]
    lines += _detail_lines(d)
    lines += footer(payload)
    return "\n".join(lines)


def register_tools(mcp):

    @mcp.tool()
    async def sustainability_reports(company: str, from_year: int | None = None, to_year: int | None = None,
                                     year: int | None = None, format: str = "md") -> str:
        """desc: 지속가능경영보고서 목록 + 한 건의 공시 원문 — 작성기준·검증기관·보고 대상 기간·목차·회사 공개처·첨부 PDF 주소.
        when: "보고서 냈어?", "GRI 기준 썼나", "검증은 누가", "보고서 목차", "보고서 PDF 어디서 받나", "무슨 기간을 다루나".
        rule: 목록은 KRX 포털이 거래소 공시(KIND)에서 집계한 것이다. 없다고 나와도 회사가 자사 사이트에만 올렸을 수 있다. 접수번호는 KIND 번호이지 DART 번호가 아니다 — 같은 번호로 DART 를 열면 다른 공시가 나온다. 원문 서식은 year 로 고른 한 건(비우면 최신)만 읽는다. PDF 본문은 읽지 않고 주소만 준다.
        params: company, from_year/to_year(목록 기간 YYYY, 선택), year(원문을 읽을 보고서 연도, 비우면 최신), format(md|json)
        ref: company, esg_ratings, esg_disclosures
        """
        payload = await build_sustainability_reports_payload(company, from_year=from_year, to_year=to_year,
                                                            year=year)
        if format == "json":
            return as_pretty_json(payload)
        if payload["status"] in ("ambiguous", "error"):
            return candidates_table(payload, "sustainability_reports")
        return _render(payload)
