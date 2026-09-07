"""governance_report — 기업지배구조보고서 원문(세부원칙 답변·서식 표·미준수 사유)."""

from __future__ import annotations

from open_esg_korea.services.contracts import as_pretty_json
from open_esg_korea.services.governance_report_payload import build_governance_report_payload
from open_esg_korea.tools._shared import candidates_table, dash, footer, head

#: md 표 한 개의 행 상한. 서식 표도 이사·주총 안건이 많으면 길어진다 — 전부는 json 으로 준다.
_MAX_ROWS = 40


def _md_table(table: dict) -> list[str]:
    """머리행이 여러 단이면 세로로 이어 붙인다(「출석률 (%) 당해연도」) — md 표는 머리가 한 줄뿐이다."""
    width = max((len(r) for r in table["header"] + table["rows"]), default=0)
    if not width:
        return []
    if table["header"]:
        cols = [" ".join(dict.fromkeys(c for c in (row[i] if i < len(row) else "" for row in table["header"]) if c))
                for i in range(width)]
    else:
        cols = [""] * width
    lines = ["| " + " | ".join(c or " " for c in cols) + " |", "|" + "---|" * width]
    for row in table["rows"][:_MAX_ROWS]:
        cells = [(row[i] if i < len(row) else "").replace("|", "\\|") for i in range(width)]
        lines.append("| " + " | ".join(cells) + " |")
    if len(table["rows"]) > _MAX_ROWS:
        lines.append(f"\n_{len(table['rows']) - _MAX_ROWS}행 생략 — 전부 보려면 `format=\"json\"`._")
    return lines


def _filing_lines(d: dict) -> list[str]:
    f = d.get("filing") or {}
    if not f:
        return []                       # 제출 이력 자체가 없다 — 「보고서: -」 로 있는 척하지 않는다
    period = d.get("period") or {}
    lines = [f"- 보고서: {dash(f.get('title'))} · 접수 {dash(f.get('disclosed_at'))} (접수번호 `{dash(f.get('acpt_no'))}`)"]
    if period.get("start"):
        lines.append(f"- 공시대상 기간: {period['start']} ~ {period['end']}"
                     + (f" · 핵심지표 준수율 {d['compliance_rate']}%" if d.get("compliance_rate") is not None else ""))
    return lines


def _render(payload: dict) -> str:
    d = payload["data"]
    name = (d.get("company") or {}).get("name", payload.get("subject", ""))
    scope = d.get("scope", "principles")
    lines = head(f"{name} 기업지배구조보고서 원문 ({scope})", payload)
    if payload["status"] == "no_data":
        return "\n".join(lines + _filing_lines(d) + footer(payload))
    lines += _filing_lines(d)
    counts = d.get("counts") or {}
    lines.append(f"- 원문에서 읽은 것: 세부원칙 {counts.get('principles', 0)}개 · 서식 표 {counts.get('tables', 0)}개 "
                 f"· 미준수 사유 {counts.get('notes', 0)}건")
    if d.get("find"):
        lines.append(f"- 찾기: 「{d['find']}」")
    lines.append("")

    if scope == "principles":
        for p in d.get("principles", []):
            lines.append(f"## 세부원칙 {p['no']} — {p['text']}")
            lines.append(p["answer"] or "_(답변 없음)_")
            if p["notes"].get("deficiency"):
                lines.append(f"- 미진한 부분 및 그 사유: {p['notes']['deficiency']}")
            if p["notes"].get("plan"):
                lines.append(f"- 향후 계획 및 보충설명: {p['notes']['plan']}")
            if p["tables"]:
                lines.append("- 딸린 서식 표: " + ", ".join(f"표 {t}" for t in p["tables"]))
            lines.append("")
    elif scope == "tables":
        for t in d.get("tables", []):
            title = f"표 {t['no']}: {t['title']}" if t["no"] else t["title"]
            lines.append(f"## {title}" + (f" (세부원칙 {t['principle']})" if t["principle"] else ""))
            lines += _md_table(t)
            lines.append("")
    else:
        not_complied = d.get("indicators_not_complied") or []
        if not_complied:
            lines.append("미준수 핵심지표: " + ", ".join(not_complied))
            lines.append("")
        for n in d.get("notes", []):
            lines.append(f"## 세부원칙 {n['no']} — {n['text']}")
            if n["deficiency"]:
                lines.append(f"- 미진한 부분 및 그 사유: {n['deficiency']}")
            if n["plan"]:
                lines.append(f"- 향후 계획 및 보충설명: {n['plan']}")
            lines.append("")
        if not d.get("notes"):
            lines.append("원문에 적힌 미준수 사유가 없습니다 — **사유 미기재**이지 「미준수 없음」이 아닙니다.")
    lines += footer(payload)
    return "\n".join(lines)


def register_tools(mcp):

    @mcp.tool()
    async def governance_report(company: str, scope: str = "principles", year: int | None = None,
                                find: str = "", format: str = "md") -> str:
        """desc: 기업지배구조보고서 **원문** — 세부원칙 28개에 대한 회사 답변, 서식 표, 미준수 사유. KIND 원문을 읽는다.
        when: "왜 미준수인가", "집중투표제를 왜 안 하나", "CEO 승계정책 뭐라고 썼나", "이사회 출석률 표", "배당 예측가능성 미진한 사유".
        rule: governance_indicators 가 「무엇이 미준수인가」(O/X)라면 이 도구는 「왜 그런가」다. year 는 **제출연도**이고 공시대상 기간은 그 전년이다 — 둘 다 응답에 있다. 금융회사는 「지배구조 연차보고서」로 갈음해 세부원칙이 없다(no_data, 미준수가 아니다). 원문을 읽지 못하면 0개 준수가 아니라 「읽지 못함」으로 답한다.
        params: company, scope(principles|tables|notes), year(제출연도 YYYY, 선택), find(원칙번호 「4-4」·핵심원칙 「4」·키워드 「승계」, 선택), format(md|json)
        ref: governance_indicators, governance_policies, esg_disclosures
        """
        payload = await build_governance_report_payload(company, scope=scope, year=year, find=find)
        if format == "json":
            return as_pretty_json(payload)
        if payload["status"] in ("ambiguous", "error"):
            return candidates_table(payload, "governance_report")
        return _render(payload)
