"""기업지배구조보고서 원문 파서 — KIND 본문 HTML → 세부원칙 답변·서식 표·미준수 사유.

Why 정규식: 문서가 5~12MB 다(삼성전자는 자유편집 표 한 개가 3.7MB). 다행히 KRX 서식 원본이라 구조가 기계적이다 —
원칙마다 `<div id="DetailedPrinciple_4-4">`, 서식 표마다 `<table-group aclass="krx-cg_…"><table class="fact-table">`.
lxml 을 새로 들이지 않고 GIR 파서와 같은 방식으로 읽는다(의존은 httpx 하나뿐).

무엇이 서식 표인가: `aclass` 가 `krx-cg_` 로 시작하는 것만이다. 나머지 `table-group` 은 회사가 자유편집한 표라
회사마다 열이 다르다 — 표로 돌려주지 않는다(OPM 과 같은 규칙).

주의 — **파싱 0건은 「읽지 못함」이지 「0개 준수」가 아니다.** 이 모듈은 값을 지어내지 않고 빈 목록을 돌려주며,
판정(`no_data` 인지 `bad_response` 인지)은 부르는 쪽이 `form` 과 개수를 보고 한다.
"""

from __future__ import annotations

import html as htmllib
import re
from typing import Any

from open_esg_korea.krx import codes

#: 서식이 답변 자리에 미리 적어 둔 안내문 — 회사 답변이 아니다.
_GUIDE_MARK = "상기 세부원칙에 대한 준수여부"
#: 답변 자리에 이것만 있으면 빈 값이다(내용이 아니라 「해당 없음」 표시).
_EMPTY_ANSWERS = {"-", "－", "해당사항없음", "해당사항 없음", "해당없음", "해당 없음", "N/A", "없음"}

_TAG_RE = re.compile(r"<[^>]+>")
_PRINCIPLE_SPLIT_RE = re.compile(r'<div id="(?:DetailedPrinciple|CorePrinciple)_')
_PRINCIPLE_RE = re.compile(r'<div id="DetailedPrinciple_(\d+-\d+)"')
_HEADING_RE = re.compile(r'class="toc-level1"[^>]*>\s*\[(\d{6})\]\s*\(세부원칙\s*\d+-\d+\)\s*-?\s*(.*?)</span>', re.S)
_LABEL_RE = re.compile(r'<span class="concept-label"[^>]*>(.*?)</span>', re.S)
_TEXTBOX_RE = re.compile(r'<td[^>]*class="[^"]*single-textbox[^"]*"[^>]*>(.*?)</td>', re.S)
_TABLE_NAME_RE = re.compile(r'<p class="table-name">(.*?)</p>\s*<table-group([^>]*)>', re.S)
_ACLASS_RE = re.compile(r'aclass="([^"]*)"')
_TABLE_NO_RE = re.compile(r"표\s*(\d+-\d+-\d+)\s*[:：]?\s*(.*)")
_CELL_RE = re.compile(r"<(th|td)([^>]*)>(.*?)</\1>", re.S)
_ROW_RE = re.compile(r"<tr\b[^>]*>(.*?)</tr>", re.S)
_SPAN_RE = re.compile(r'\b(rowspan|colspan)="(\d*)"')
_RATE_RE = re.compile(r'class="[^"]*bg_percent[^"]*"[^>]*value="([\d.]+)"')
_PERIOD_RE = re.compile(r"공시대상 기간 시작일\s*(\d{4}-\d{2}-\d{2}).*?공시대상 기간 종료일\s*(\d{4}-\d{2}-\d{2})", re.S)
_COMPANY_RE = re.compile(r"1\.\s*기업명\s*(.+?)\s*2\.\s*공시대상", re.S)

#: 15개 핵심지표 표의 개념 코드. 이 표만 지표로 읽는다.
INDICATOR_CONCEPT = "krx-cg_ComplianceStatusWithKeyIndicatorsOfCorporateGovernanceAbstract"
#: 미준수 사유가 실제로 적히는 자리 — 지표 표의 「비고」는 대개 비어 있다(삼성전자 2025: 15칸 전부).
_NOTE_LABELS = {"(1) 미진한 부분 및 그 사유": "deficiency", "(2) 향후 계획 및 보충설명": "plan"}


def text_of(fragment: str) -> str:
    """태그를 지운 한 줄. 태그를 빈칸으로 바꾸므로 `…합니다<span>.</span>` 가 「합니다 .」 이 된다 — 그 자리만 붙인다."""
    plain = " ".join(htmllib.unescape(_TAG_RE.sub(" ", fragment)).replace("\xa0", " ").split())
    plain = re.sub(r"\s+([.,;:!?%)\]}」』])", r"\1", plain)
    return re.sub(r"([(\[{「『])\s+", r"\1", plain)


def _answer(value: str) -> str:
    """「-」「해당사항없음」은 답변이 아니라 빈 값이다."""
    value = value.strip()
    return "" if value in _EMPTY_ANSWERS else value


def _span(attrs: str, name: str) -> int:
    """`rowspan=""`·`colspan="0"` 이 실제로 온다 — 둘 다 1 로 읽는다."""
    for key, raw in _SPAN_RE.findall(attrs):
        if key == name:
            return int(raw) if raw.isdigit() and int(raw) > 0 else 1
    return 1


def _table_body(html: str, start: int) -> str:
    """`<table …>` 부터 짝이 맞는 `</table>` 까지 — 자유편집 표가 안에 겹쳐 있어도 잘못 끊지 않는다."""
    depth, pos = 0, start
    for m in re.finditer(r"<table\b|</table>", html[start:]):
        depth += 1 if m.group(0) == "<table" else -1
        if depth == 0:
            return html[start:start + m.end()]
        pos = start + m.end()
    return html[start:pos] if pos > start else ""


def parse_grid(table_html: str) -> tuple[list[list[str]], list[list[str]]]:
    """표 HTML → (머리행, 몸통행). rowspan·colspan 을 실제 칸으로 펼친다.

    서식 표의 머리는 3단까지 겹쳐 있다(출석률 표) — 펼치지 않으면 열이 어긋난다.
    thead·tbody 를 따로 편다: 몸통 첫 칸이 `<th>` 인 표(핵심지표 표)가 있어 태그로는 구분되지 않고,
    머리행의 rowspan 값이 실제보다 크게 적혀 있어(서식 내보내기 버릇) 몸통 첫 줄을 밀어낸다.
    """
    thead = re.search(r"(?s)<thead\b[^>]*>(.*?)</thead>", table_html)
    tbody = re.search(r"(?s)<tbody\b[^>]*>(.*?)</tbody>", table_html)
    if thead or tbody:
        return (_expand(thead.group(1)) if thead else [],
                _expand(tbody.group(1), rowspan=False) if tbody else [])
    return _split_by_tag(table_html)


def _expand(section_html: str, *, rowspan: bool = True) -> list[list[str]]:
    """한 구역(thead 또는 tbody)의 행 → 칸이 맞춰진 격자.

    머리행의 rowspan 이 실제 단수보다 크게 적혀 있어(서식 내보내기 버릇) 빈 유령 행이 뒤에 붙는다 — 떼어낸다.
    """
    grid, _ = _grid_of(section_html, rowspan=rowspan)
    while grid and not any(cell.strip() for cell in grid[-1]):
        grid.pop()
    return grid


def _split_by_tag(table_html: str) -> tuple[list[list[str]], list[list[str]]]:
    """thead·tbody 가 없는 표 — 첫 칸이 `<th>` 인 줄을 머리로 본다(차선)."""
    grid, kinds = _grid_of(table_html)
    header = [row for i, row in enumerate(grid) if kinds.get(i) == "th"]
    body = [row for i, row in enumerate(grid) if kinds.get(i) != "th"]
    return header, body


def _grid_of(html: str, *, rowspan: bool = True) -> tuple[list[list[str]], dict[int, str]]:
    """`rowspan=False` 는 몸통용이다 — 서식 내보내기가 세로 병합을 **표시용**으로만 쓰기 때문이다.
    병합된 칸도 다음 줄에 `style="display:none" originrowspan="1"` 로 값이 그대로 다시 적혀 있어서,
    rowspan 을 따르면 그 줄만 한 칸씩 밀린다(주주환원 표 1-5-1-1 에서 실측).
    """
    grid: list[list[str | None]] = []
    kinds: dict[int, str] = {}
    r = -1
    for row_html in _ROW_RE.findall(html):
        cells = _CELL_RE.findall(row_html)
        if not cells:
            continue
        r += 1
        while len(grid) <= r:
            grid.append([])
        col = 0
        for tag, attrs, body in cells:
            while col < len(grid[r]) and grid[r][col] is not None:
                col += 1
            cs = _span(attrs, "colspan")
            rs = _span(attrs, "rowspan") if rowspan else 1
            value = text_of(body)
            for dr in range(rs):
                while len(grid) <= r + dr:
                    grid.append([])
                row = grid[r + dr]
                while len(row) < col + cs:
                    row.append(None)
                for dc in range(cs):
                    row[col + dc] = value if (dr, dc) == (0, 0) else ""
            col += cs
        kinds[r] = cells[0][0]
    return [[c or "" for c in row] for row in grid], kinds


def _tables_in(html: str, principle: str | None = None) -> list[dict[str, Any]]:
    """`<p class="table-name">` + `krx-cg_` table-group 짝만 서식 표로 읽는다."""
    tables: list[dict[str, Any]] = []
    for m in _TABLE_NAME_RE.finditer(html):
        aclass = _ACLASS_RE.search(m.group(2))
        if not aclass or not aclass.group(1).startswith("krx-cg_"):
            continue                                    # 자유편집 표 — 회사마다 열이 다르다
        start = html.find('<table class="fact-table"', m.end())
        if start == -1:
            continue
        header, body = parse_grid(_table_body(html, start))
        width = max((len(row) for row in header + body), default=0)
        header = [row + [""] * (width - len(row)) for row in header]
        body = [row + [""] * (width - len(row)) for row in body]
        name = text_of(m.group(1))
        no_match = _TABLE_NO_RE.match(name)
        tables.append({
            "no": no_match.group(1) if no_match else None,
            "title": no_match.group(2).strip() if no_match else name,
            "concept": aclass.group(1),
            "principle": principle,
            "header": header,
            "rows": body,
        })
    return tables


def _principle_blocks(html: str) -> list[tuple[str, str]]:
    """본문 → [(원칙번호, 그 원칙의 HTML)]. `DetailedPrinciple_N-M` div 사이를 잘라 쓴다."""
    bounds = [m.start() for m in _PRINCIPLE_SPLIT_RE.finditer(html)] + [len(html)]
    blocks: list[tuple[str, str]] = []
    for start, end in zip(bounds, bounds[1:]):
        m = _PRINCIPLE_RE.match(html, start)
        if m:
            blocks.append((m.group(1), html[start:end]))
    return blocks


def _note_texts(block: str) -> dict[str, str]:
    """「(1) 미진한 부분 및 그 사유」·「(2) 향후 계획 및 보충설명」 — 미준수 사유가 실제로 있는 자리."""
    notes: dict[str, str] = {}
    for m in _LABEL_RE.finditer(block):
        key = _NOTE_LABELS.get(text_of(m.group(1)))
        if not key:
            continue
        box = _TEXTBOX_RE.search(block, m.end(), m.end() + 4000)
        value = _answer(text_of(box.group(1))) if box else ""
        if value:
            notes[key] = value
    return notes


def parse_principles(html: str) -> list[dict[str, Any]]:
    """세부원칙 28개 → 번호·절 코드·원칙문·회사 답변·미준수 사유·딸린 서식 표 번호."""
    principles: list[dict[str, Any]] = []
    for no, block in _principle_blocks(html):
        heading = _HEADING_RE.search(block)
        answer = ""
        guide = block.find(_GUIDE_MARK)
        if guide != -1:
            box = _TEXTBOX_RE.search(block, guide)
            if box:
                answer = _answer(text_of(box.group(1)))
        tables = _tables_in(block, principle=no)
        principles.append({
            "no": no,
            "core": int(no.split("-")[0]),
            "section": heading.group(1) if heading else None,
            "text": text_of(heading.group(2)) if heading else "",
            "answer": answer,
            "notes": _note_texts(block),
            "tables": [t["no"] for t in tables if t["no"]],
        })
    return principles


def parse_tables(html: str) -> list[dict[str, Any]]:
    """서식 표 전부 — 원칙 안의 것은 `principle` 이 붙고, 앞머리 절의 것(핵심지표 표 등)은 None."""
    tables: list[dict[str, Any]] = []
    seen_at: set[int] = set()
    for no, block in _principle_blocks(html):
        tables.extend(_tables_in(block, principle=no))
        seen_at.add(html.find(block))
    head_end = html.find('<div id="DetailedPrinciple_')
    tables = _tables_in(html[:head_end] if head_end != -1 else html) + tables
    return tables


def parse_indicators(html: str) -> list[dict[str, Any]]:
    """15개 핵심지표 표 → 지표별 당기·직전기 O/X 와 비고.

    포털 `governance_indicators` 와 같은 값이다 — 여기서 읽는 이유는 **비고** 때문이다.
    """
    table = next((t for t in parse_tables(html) if t["concept"] == INDICATOR_CONCEPT), None)
    if table is None:
        return []
    rows: list[dict[str, Any]] = []
    for i, cells in enumerate(table["rows"], start=1):
        if len(cells) < 3 or not cells[0]:
            continue
        rows.append({"no": i, "label": cells[0], "current": cells[1] or None,
                     "previous": cells[2] or None, "note": (cells[3] if len(cells) > 3 else "")})
    return rows


def parse_report(html: str, *, form: str | None = None) -> dict[str, Any]:
    """본문 HTML → 보고서 한 벌. `form` 은 KIND 서식번호(`KindClient.document()` 의 `form_no`).

    `kind` 는 셋 중 하나다:
      - `gov_report`    기업지배구조보고서 서식(세부원칙 28개)
      - `annual_report` 금융회사 지배구조 연차보고서로 갈음 — 본문은 안내문뿐, 내용은 첨부 PDF 에 있다
      - `unknown`       서식번호도 세부원칙도 없다(차단 페이지·정정 전 문서일 수 있다)
    """
    principles = parse_principles(html)
    if form == codes.KIND_FORM_ANNUAL_REPORT or (not principles and codes.KIND_ANNUAL_REPORT_MARK in html[:4000]):
        kind = "annual_report"
    elif principles:
        kind = "gov_report"
    else:
        kind = "unknown"

    head = text_of(html[:html.find('<div id="DetailedPrinciple_')] if principles else html[:20000])
    company = _COMPANY_RE.search(head)
    period = _PERIOD_RE.search(head)
    rate = _RATE_RE.search(html)
    return {
        "kind": kind,
        "form_no": form,
        "company_name": company.group(1).strip() if company else None,
        "period_start": period.group(1) if period else None,
        "period_end": period.group(2) if period else None,
        "compliance_rate": float(rate.group(1)) if rate else None,
        "principles": principles,
        "tables": parse_tables(html) if kind == "gov_report" else [],
        "indicators": parse_indicators(html) if kind == "gov_report" else [],
    }
