"""sustainability_report_text — 지속가능경영보고서 PDF 본문에서 찾아 읽기."""

from __future__ import annotations

from open_esg_korea.services.contracts import as_pretty_json
from open_esg_korea.services.report_text import build_report_text_payload
from open_esg_korea.tools._shared import candidates_table, dash, footer, head

#: 한 번에 보여줄 쪽 본문의 글자 상한. 넘으면 잘라 내고 그렇다고 말한다.
_MAX_PAGE_CHARS = 6000


def _report_lines(d: dict) -> list[str]:
    r = d.get("report") or {}
    att = d.get("attachment") or {}
    lines = [f"- 보고서: {dash(r.get('report_title'))} ({dash(r.get('year'))})"
             + (f" · {d['page_count']}쪽" if d.get("page_count") else "")]
    if att:
        lines.append(f"- 원문 PDF: [{att['name']}]({att['url']})")
    return lines


def _render(payload: dict) -> str:
    d = payload["data"]
    name = (d.get("company") or {}).get("name", payload.get("subject", ""))
    lines = head(f"{name} 지속가능경영보고서 본문", payload) + _report_lines(d)

    if payload["status"] == "no_data":
        return "\n".join(lines + footer(payload))

    mode = d.get("mode")
    if mode == "find":
        found = d.get("match_pages") or []
        lines.append(f"- 「{d['find']}」: {d.get('total_hits', 0)}건"
                     + (f" · {len(found)}쪽 {found}" if found else " — 걸린 쪽 없음"))
        lines.append("")
        for m in d.get("matches") or []:
            lines.append(f"### {m['page']}쪽 ({m['hits']}건)")
            lines += [f"> …{s}…" for s in m["snippets"]]
            lines.append("")
        if d.get("match_pages"):
            first = d["match_pages"][0]
            lines.append(f"_쪽 전체를 보려면_ `page={first}`")
    elif mode == "page":
        lines += ["", f"### {d['page']}쪽" + ("" if d.get("aligned") else " (평문)"), "", "```"]
        text = (d.get("page_text") or "").strip()
        lines.append(text[:_MAX_PAGE_CHARS])
        if len(text) > _MAX_PAGE_CHARS:
            lines.append(f"… {len(text) - _MAX_PAGE_CHARS}자 생략")
        lines.append("```")
    else:
        lines += ["", "**공시에 적힌 보고 내용(목차)**", "", "```", d.get("toc", ""), "```", "",
                  '_본문에서 찾으려면_ `find="Scope 3"` _· 쪽을 보려면_ `page=73`']
    lines += footer(payload)
    return "\n".join(lines)


def register_tools(mcp):

    @mcp.tool()
    async def sustainability_report_text(company: str, find: str = "", page: int | None = None,
                                         year: int | None = None, format: str = "md") -> str:
        """desc: 지속가능경영보고서 **PDF 본문**에서 찾아 읽는다 — 키워드가 몇 쪽에 있는지, 그 대목이 뭐라고 쓰였는지.
        when: "Scope 3 뭐라고 썼나", "재생에너지 목표가 뭔가", "협력회사 인권 실사 내용", "그 표 보여줘", "보고서 목차".
        rule: 회사가 공시에 첨부한 PDF 를 읽는다(첨부가 없으면 no_data — 회사 사이트에만 올렸을 수 있다). 검색은 공백을 무시한다 — 원문이 자간을 벌려 조판해 「온실가스 배출량」처럼 띄어져 있기 때문이다. 못 찾으면 「없다」가 아니라 「이 표기로 못 찾았다」이다. 이미지 PDF 는 읽지 못한다(OCR 하지 않는다). **표의 수치를 기계적으로 뽑지 않는다** — 납작해진 원문을 주니 어느 연도·부문 값인지는 원문 PDF 로 확인하라.
        params: company, find(키워드, 선택), page(쪽 번호 1부터, 선택), year(보고서 연도, 비우면 최신), format(md|json)
        ref: sustainability_reports, governance_report, ghg_emissions
        """
        payload = await build_report_text_payload(company, find=find, page=page, year=year)
        if format == "json":
            return as_pretty_json(payload)
        if payload["status"] in ("ambiguous", "error"):
            return candidates_table(payload, "sustainability_report_text")
        return _render(payload)
