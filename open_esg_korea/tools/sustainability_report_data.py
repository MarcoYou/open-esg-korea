"""sustainability_report_data — 지속가능경영보고서 부록(데이터 장) 표를 행·열로."""

from __future__ import annotations

import csv
import io

from open_esg_korea.services.contracts import as_pretty_json
from open_esg_korea.services.report_data import build_report_data_payload
from open_esg_korea.tools._shared import candidates_table, dash, footer, head

#: md 로 보여줄 행 상한 — 넘으면 csv/json 이나 find·page 로 좁히라고 말한다.
_MAX_MD_ROWS = 300
#: csv 로 한 번에 싣는 값 상한. 데이터 장 39쪽(현대모비스 2026)이면 값 6천 개·62만 자라 대화에 들어가지 않는다 —
#: 쪽 경계에서 끊고 마지막 줄에 이어 부를 쪽 범위를 적는다.
_MAX_CSV_VALUES = 2500


def _cell(text: str) -> str:
    return str(text).replace("|", r"\|").replace("\n", " ")


def _label(row: dict) -> str:
    return f"{row['parent']} › {row['label']}" if row.get("parent") else row["label"]


def _table_lines(t: dict, budget: int) -> tuple[list[str], int]:
    keys = [c["key"] for c in t["columns"]]
    ok = [r for r in t["rows"] if r["status"] == "ok"]
    checks = [r for r in t["rows"] if r["status"] == "check"]
    title = t["title"] or "(제목 없음)"
    lines = ["", f"### {t['page']}쪽 · {_cell(title)}", ""]
    if ok:
        lines += ["| 행 | 단위 | " + " | ".join(_cell(k) for k in keys) + " |",
                  "|---|---|" + "---:|" * len(keys)]
        for r in ok[:budget]:
            mark = " ↕" if r.get("label_from") == "adjacent_line" else ""
            lines.append(f"| {_cell(_label(r))}{mark} | {_cell(r['unit'])} | "
                         + " | ".join(_cell(r["values"].get(k, "")) for k in keys) + " |")
        budget -= min(len(ok), budget)
    if checks:
        lines += ["", f"_검사에 걸려 값을 비운 행 {len(checks)}개 — 원문 줄:_"]
        for r in checks[:max(budget, 3)]:
            lines.append(f"- {_cell(_label(r)) or '(이름 없음)'}: `{r['line'][:160]}` — {r['problems'][0] if r['problems'] else ''}")
    if t.get("footnotes"):
        lines.append("")
        lines += [f"<sub>{k}) {_cell(v)[:200]}</sub>  " for k, v in list(t["footnotes"].items())[:6]]
    return lines, budget


def _render(payload: dict) -> str:
    d = payload["data"]
    name = (d.get("company") or {}).get("name", payload.get("subject", ""))
    lines = head(f"{name} 지속가능경영보고서 부록 표", payload)
    r = d.get("report") or {}
    att = d.get("attachment") or {}
    lines.append(f"- 보고서: {dash(r.get('report_title'))} ({dash(r.get('year'))})"
                 + (f" · {d['page_count']}쪽" if d.get("page_count") else "")
                 + (f" · 데이터 장 {d['data_section'][0]}–{d['data_section'][1]}쪽" if d.get("data_section") else ""))
    if att:
        lines.append(f"- 원문 PDF: [{att['name']}]({att['url']})")
    if payload["status"] == "no_data":
        for m in d.get("separate_book_mentions") or []:
            lines.append(f"  - {m['page']}쪽: …{_cell(m['snippet'])[:120]}…")
        return "\n".join(lines + footer(payload))
    c = d.get("counts") or {}
    lines.append(f"- 표 {c.get('tables', 0)}개 · 행 {c.get('rows', 0)}개(검사 통과 {c.get('ok_rows', 0)} · "
                 f"원문 확인 필요 {c.get('check_rows', 0)}) · 값 {c.get('values', 0)}개"
                 + (f" · 「{d['find']}」로 좁힘" if d.get("find") else ""))
    if d.get("scope_note"):
        lines.append(f"- {d['scope_note']}")
    lines.append("- 행 이름의 `A › B` 는 들여쓰기로 본 상위 행, `↕` 는 행 이름이 위·아래 줄에 따로 있던 표입니다.")
    budget = _MAX_MD_ROWS
    for t in d.get("tables") or []:
        if budget <= 0:
            lines += ["", f"_행이 많아 여기서 줄였습니다 — `format=\"csv\"`(엑셀용) 나 `format=\"json\"`, 또는 `find`·`page` 로 "
                          "좁혀 부르세요._"]
            break
        chunk, budget = _table_lines(t, budget)
        lines += chunk
    return "\n".join(lines + footer(payload))


#: 원문 PDF 주소(200자 안팎)를 줄마다 되풀이하면 데이터 장 39쪽짜리 보고서가 170만 자가 됐다 — 짧은 KIND 접수번호로 잇는다.
CSV_COLUMNS = ["회사", "종목코드", "보고서연도", "공시접수번호", "쪽", "표", "상위행", "행", "단위", "열", "연도", "값",
               "상태", "각주", "원문줄", "검사사유"]


def _csv(payload: dict) -> str:
    """엑셀에 바로 붙는 긴 형식 — 한 줄에 값 하나. 검사에 걸린 행은 값 없이 원문 줄과 사유를 한 줄로 싣는다."""
    d = payload["data"]
    comp = d.get("company") or {}
    rep = d.get("report") or {}
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(CSV_COLUMNS)
    base = [comp.get("name", ""), comp.get("isu_cd", ""), rep.get("year", ""), rep.get("acpt_no", "")]
    tables = d.get("tables") or []
    pages = sorted({t["page"] for t in tables})
    written, last_page = 0, None
    for page in pages:
        page_values = sum(len(r["values"]) for t in tables if t["page"] == page for r in t["rows"])
        if written and written + page_values > _MAX_CSV_VALUES:
            break
        written += page_values
        last_page = page
    cut = last_page is not None and last_page != (pages[-1] if pages else None)
    for t in tables:
        if cut and t["page"] > last_page:
            continue
        years = {c["key"]: c["year"] or "" for c in t["columns"]}
        for r in t["rows"]:
            notes = " / ".join(f"{m}) {t['footnotes'].get(m, '')}" for m in r.get("marks") or [] if m in t["footnotes"])
            if r["status"] == "ok":
                for key, value in r["values"].items():
                    w.writerow(base + [t["page"], t["title"], r.get("parent", ""), r["label"], r["unit"], key,
                                       years.get(key, ""), value, "ok", notes, "", ""])
            else:
                w.writerow(base + [t["page"], t["title"], r.get("parent", ""), r["label"], r["unit"], "", "", "",
                                   "check", notes, r["line"], " / ".join(r["problems"])])
    if cut:
        rest = [p for p in pages if p > last_page]
        w.writerow(base + ["", "", "", "", "", "", "", "", "잘림", "", "",
                           f"값이 많아 {last_page}쪽까지만 실었습니다 — 나머지는 page=\"{rest[0]}-{rest[-1]}\" "
                           f"(12쪽씩)로 이어 부르세요"])
    return buf.getvalue()


def register_tools(mcp):

    @mcp.tool()
    async def sustainability_report_data(company: str, find: str = "", page: int | str | None = None,
                                         year: int | None = None, format: str = "md") -> str:
        """desc: 지속가능경영보고서 **부록(데이터 장) 수치 표를 행·열로** 뽑는다 — 「부록 뽑아줘」「ESG 데이터 엑셀로」. 행 이름·단위·열 머리(연도·경계)·각주·쪽 번호가 붙은 **후보**다.
        when: "○○ 지속가능경영보고서 부록 표 뽑아줘", "ESG 데이터 엑셀로", "에너지 사용량 표", "용수·폐기물 연도별 수치", "여성 임직원 비율 추이".
        rule: 뒤쪽 데이터 장(ESG Data·Factbook·Facts & Figures)을 자동으로 찾아 표를 푼다. **값은 후보다** — 검사(열 머리·열 수·붙은 숫자·옆 표 값 섞임·행 이름)를 모두 통과한 행(ok)만 값을 싣고, 걸린 행(check)은 값을 비우고 원문 줄을 준다. 같은 지표가 국내/글로벌·시장/지역기반으로 여러 번 나와도 하나로 고르지 않는다 — 열 머리와 표 제목·각주를 보고 고른다. 「2025 목표」 같은 목표 열은 열 머리에 표시된다. 데이터 장을 못 찾으면(본문에 흩어진 보고서·데이터북 별도 발간) no_data 와 함께 단서를 준다 — 그때는 sustainability_report_text 로 찾아 page= 로 그 쪽을 푼다. 실측(28개 보고서): 30개사 작업에서 보고서를 읽고 옮긴 값 271개와 대조해 83% 가 검사 통과 칸에서 맞는 해로 나왔고, 검사를 통과했는데 해가 틀린 칸은 0 이었다.
        params: company, find(행 이름·상위 행·표 제목에서 찾기, 공백 무시, 선택), page(쪽 번호 또는 범위 "139-148" — 12쪽까지, 비우면 데이터 장 전체), year(보고서 연도, 비우면 최신), format(md|csv|json — csv 는 엑셀용 긴 형식: 한 줄에 값 하나)
        ref: sustainability_report_text, sustainability_reports, ghg_emissions
        """
        payload = await build_report_data_payload(company, find=find, page=page, year=year)
        if format == "json":
            return as_pretty_json(payload)
        if payload["status"] in ("ambiguous", "error"):
            return candidates_table(payload, "sustainability_report_data")
        if format == "csv" and payload["status"] == "exact":
            return _csv(payload)
        return _render(payload)
