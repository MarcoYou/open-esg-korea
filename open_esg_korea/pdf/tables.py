"""수치 표 → 행 **후보**. 글자 좌표(pdfplumber words)로 표를 풀어 「행 × 열 머리(연도·경계) → 값」을 만든다.

왜 격자(`extract.page_tables`)가 아니라 이것인가 (2026-09-22~24 실측):
  - 이 서식은 괘선이 없어 격자는 글자 정렬로 열을 가르는데, 한 쪽에 표가 **좌우로** 놓이면 두 표가 한 행으로
    이어지고 숫자가 갈라진다(실측 노트 11).
  - 열은 머리글 위치보다 **숫자의 오른쪽 끝**으로 잡는 편이 맞다 — 숫자는 오른쪽 정렬이고, 머리글은 두 열 위에
    걸치기도 한다(「2023년」 아래 DX부문·DS부문).
  - 좌우로 붙은 두 표는 **높이가 다르다**(삼성생명 p131: 오른쪽 표 머리가 한 줄 위, 그것도 두 줄로 갈림). 그래서
    표는 「연도 머리 묶음」마다 따로 세우고, 몸통은 **자기 가로 범위 안에서** 다음 머리가 나올 때까지로 본다.

**값은 후보다.** 행마다 검사를 하고, 모두 통과한 행(`status="ok"`)만 값을 싣는다. 하나라도 걸리면
(`status="check"`) 값을 비우고 그 줄의 원문을 준다 — 조용히 틀린 값을 주지 않는다. 같은 지표가 한 보고서에
여러 번(국내/글로벌, 시장/지역기반) 나오므로 하나로 고르지 않고 전부 준다.

순수 함수만 둔다 — 입력은 쪽의 글자 목록(`list[dict]`: text·x0·x1·top·bottom), 네트워크도 PDF 도 모른다.
"""

from __future__ import annotations

import re
import statistics
from dataclasses import asdict, dataclass, field
from typing import Any

#: 연도 머리. 「2023」「2023년」「FY2023」, 각주 표지가 붙은 「2024²⁾」「20241)」은 표지를 떼고 본다.
_YEAR_RE = re.compile(r"^(?:FY|'|’)?(20[12]\d)(?:년|년도|\.12)?(?:\d\)|[¹²³⁴⁵⁶⁷⁸⁹*]+)?$")
#: 값. 쉼표 세 자리 묶음·소수·괄호 음수·퍼센트. 「2)」 같은 각주 표지나 「(Scope 1, 2)」 의 「1,」 는 값이 아니다 —
#: 「1,」 를 값으로 읽어 머리 줄을 값 줄로 보고 표 경계를 잘못 그었다(삼성전자 p72).
_NUM_RE = re.compile(r"^[-−]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?%?$|^\((?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?\)$")
#: 빈 칸 표시 — 「-」「~」「N/A」.
_DASH_RE = re.compile(r"^[-–—−~～]$|^N/?A$|^n/?a$")
#: 각주 표지 — 「1)」「*」「※」「¹」. 라벨 끝에 붙어 나오기도 한다(「사용량1)」).
_FOOT_RE = re.compile(r"^(?:\d{1,2}\)|\*{1,3}\d?\)?|※\d?|[¹²³⁴⁵⁶⁷⁸⁹⁰]+)$")
_TRAILING_FOOT_RE = re.compile(r"(?:\d{1,2}\)|[¹²³⁴⁵⁶⁷⁸⁹⁰]+|\*+)(?:\s*,\s*\d{1,2}\))*$")
#: 단위 토큰. 라벨 오른쪽 끝에서 이것들을 거둬 단위로 삼는다.
#: 단위 = (배수)? 뿌리 (/분모)? — 「천 톤」「만tCO2eq」「MWh/억」「tCO2eq/매출 억원」. 뿌리가 단위가 아닌
#: 「중동/아프리카」 같은 행 이름을 단위로 거두지 않게 뿌리를 정해 둔다.
_UNIT_RE = re.compile(
    r"^(?:천|만|백만|십억|억|천만|조)?\s*(?:톤(?:CO2e|CO₂e)?|ton|Ton|TON|t?CO[₂2]?-?eq?|"
    r"MWh|GWh|kWh|TJ|GJ|MJ|TOE|toe|㎥|m3|m³|ML|kL|%|명|원|건|시간|개|개사|회|점|kg|mg|ppm|㎏|"
    r"USD|달러|km|대|%p|‰)(?:/[^\s]{1,12})?$")
_MULTIPLIER = ("천", "만", "백만", "십억", "억", "조")
#: 목표·계획 열 표시. 「목표관리제」는 제도 이름이지 목표가 아니다(우리금융지주 p156).
_PLAN_RE = re.compile(r"목표(?!관리)|계획|전망|예상|추정|Target|target|Goal|goal|Plan|plan")
_UNIT_NOTE_RE = re.compile(r"^\(?\s*단위\s*[:：]")
_LETTER = re.compile(r"[가-힣A-Za-z]")
_HANGUL = re.compile(r"[가-힣]")
_ENERGY_UNIT = re.compile(r"^(?:[kMGT]?J|[kMGT]Wh|TOE|toe)$")
_HEADER_WORDS = ("구분", "단위", "지표", "지표명", "항목")
_DOUBLED_RE = re.compile(r"([A-Z])\1([A-Z])\2([A-Z])\3")

_LINE_TOL = 3.0          # 같은 줄로 볼 세로 차이(pt)
_COL_TOL = 7.0           # 같은 열로 볼 숫자 오른쪽 끝 차이(pt)
_ASSIGN_TOL = 9.0        # 값을 열에 붙일 때 허용하는 오른쪽 끝 차이(pt)
_PHRASE_GAP = 4.5        # 머리글 낱말을 한 덩어리로 이을 때 허용하는 틈(pt) — 띄어쓰기 한 칸
_ADJ_MAX_GAP = 12.0      # 값 줄과 옆 「이름만 있는 줄」의 위쪽 끝 거리 상한(pt) — 멀면 쪽 번호·다른 덩어리다
_SPLIT_GAP = 0.8         # 값 두 개가 이만큼 붙어 있으면 한 숫자가 갈린 것으로 의심한다(pt)


@dataclass
class Column:
    key: str                      # 「DX부문·2025」 같은 열 머리 경로
    year: str | None
    path: list[str]
    right: float                  # 이 열 숫자의 오른쪽 끝(중앙값)


@dataclass
class Row:
    label: str
    unit: str
    marks: list[str]
    indent: float
    values: dict[str, str]
    status: str                   # ok | check
    problems: list[str]
    line: str                     # 그 줄의 원문(검사에 걸리면 이것을 본다)
    label_from: str = "same_line"  # same_line | adjacent_line(라벨이 위·아래 줄에 따로 있던 표)
    parent: str = ""               # 들여쓰기로 본 상위 행(「자발적 이직률」 아래 「국내」) — 같은 이름 행을 가른다


@dataclass
class Table:
    page: int
    title: str
    columns: list[Column]
    rows: list[Row] = field(default_factory=list)
    footnotes: dict[str, str] = field(default_factory=dict)
    header_problems: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"page": self.page, "title": self.title,
                "columns": [{"key": c.key, "year": c.year, "path": c.path} for c in self.columns],
                "rows": [asdict(r) for r in self.rows], "footnotes": self.footnotes,
                "header_problems": self.header_problems}


# ── 토큰 판별 ─────────────────────────────────────────────────────────────────
def _year(text: str) -> str | None:
    m = _YEAR_RE.match(text.strip())
    return m.group(1) if m else None


def _is_value(text: str) -> bool:
    t = text.strip()
    return bool(_NUM_RE.match(t) or _DASH_RE.match(t)) and _year(t) is None


def _is_mark(text: str) -> bool:
    return bool(_FOOT_RE.match(text.strip()))


def _center(w: dict) -> float:
    return (w["x0"] + w["x1"]) / 2


def _lines(words: list[dict]) -> list[list[dict]]:
    """세로 위치로 줄을 묶는다(각 줄은 왼쪽→오른쪽)."""
    out: list[list[dict]] = []
    tops: list[float] = []
    for w in sorted(words, key=lambda w: (w["top"], w["x0"])):
        if out and abs(w["top"] - tops[-1]) <= _LINE_TOL:
            out[-1].append(w)
        else:
            out.append([w])
            tops.append(w["top"])
    return [sorted(line, key=lambda w: w["x0"]) for line in out]


def _merge_subscripts(line: list[dict]) -> list[dict]:
    """「tCO 2 eq」「CO 2 e」처럼 아래첨자가 따로 떨어진 단위를 한 토큰으로 — 「2」를 값으로 읽지 않게.
    「m」에 딱 붙은 작은 「3」「2」(m³ · km²)도 합친다 — 위첨자가 제 줄에 오면 값 열의 숫자로 읽혔다(삼성생명 p132)."""
    out: list[dict] = []
    for w in line:
        prev = out[-1] if out else None
        if prev and re.fullmatch(r"t?CO|tCO2|CO2|t?CO₂", prev["text"]) and w["x0"] - prev["x1"] <= 5.0 \
                and re.fullmatch(r"2|₂|eq|e|-eq|e\)|eq\)", w["text"]):
            out[-1] = {**prev, "text": prev["text"] + w["text"], "x1": w["x1"]}
        elif prev and re.fullmatch(r"(?:.*/)?[kcdNS]?m", prev["text"]) and re.fullmatch(r"[23]", w["text"]) \
                and w["x0"] - prev["x1"] <= 1.0 and (w["bottom"] - w["top"]) <= 0.75 * (prev["bottom"] - prev["top"]):
            out[-1] = {**prev, "text": prev["text"] + w["text"], "x1": w["x1"]}
        else:
            out.append(dict(w))
    return out


def _phrases(line: list[dict]) -> list[dict]:
    """띄어쓰기 한 칸 거리의 낱말을 한 덩어리로 — 「국내 자회사」가 「자회사」로 쪼개지지 않게."""
    out: list[dict] = []
    for w in line:
        if out and w["x0"] - out[-1]["x1"] <= _PHRASE_GAP and not _year(w["text"]) and not _year(out[-1]["text"]):
            prev = out[-1]
            out[-1] = {**prev, "text": prev["text"] + " " + w["text"], "x1": w["x1"], "words": prev["words"] + [w]}
        else:
            out.append({**w, "words": [w]})
    return out


def _split_year_groups(line: list[dict]) -> list[list[dict]]:
    """한 줄의 연도 머리를 표별로 가른다 — 연도가 되돌아가거나(2025→2023), 연도 사이에 **표 제목**
    (세 글자 이상 글자 덩어리)이 끼면 새 표다. 같은 해가 이어지는 것(2024 2024 = 성과·목표)은 한 표다."""
    groups: list[list[dict]] = []
    last_year: str | None = None
    between = ""
    for w in line:
        y = _year(w["text"])
        if y is None:
            if groups and _LETTER.search(w["text"]):
                between += w["text"]
            continue
        titled = len(re.sub(r"[^가-힣A-Za-z]", "", between)) >= 3
        if not groups or (last_year is not None and y < last_year) or titled:
            groups.append([w])
        else:
            groups[-1].append(w)
        last_year, between = y, ""
    return [g for g in groups if g]


def _cluster(values: list[float], tol: float) -> list[list[float]]:
    groups: list[list[float]] = []
    for x in sorted(values):
        if groups and x - groups[-1][-1] <= tol:
            groups[-1].append(x)
        else:
            groups.append([x])
    return groups


def _strip_marks(text: str) -> str:
    """머리글 끝의 각주 표지(「HD한국조선해양 3)」「목표2)」)를 뗀다."""
    return re.sub(r"\s*(?:\d{1,2}\)|[¹²³⁴⁵⁶⁷⁸⁹*]+)(?:\s*,\s*\d{1,2}\))*$", "", text).strip()


def _open_parens(text: str) -> int:
    return text.count("(") - text.count(")")


def _split_label(texts: list[str]) -> tuple[str, str, list[str]]:
    """라벨 낱말 → (라벨, 단위, 각주 표지). 단위는 오른쪽 끝에서 거둔다.

    끝의 「1)」은 각주 표지일 수도, 괄호를 닫는 글자일 수도 있다(「직접 배출량(Scope 1)」). 앞에 열린 괄호가 있으면
    괄호를 닫는 것으로 보고 이름에 남긴다 — 표지로 떼면 「직접 배출량(Scope」 가 된다(한화오션 p109).
    """
    marks: list[str] = []
    unit: list[str] = []
    # 이름 **가운데** 낀 표지 — 분류 칸과 항목이 한 줄로 이어진 표(「수료 인원 1) 해외법인」 삼성SDI p83 · 「참석률1)
    # 사적금전대차」)는 표지 뒤에 이름이 더 온다. 열린 괄호를 닫는 「1)」(「(Scope 1) 배출량」)은 남긴다.
    kept: list[str] = []
    for k, t in enumerate(texts):
        more = any(_LETTER.search(x) and not _is_mark(x) and not _UNIT_RE.match(x.rstrip(",/")) for x in texts[k + 1:])
        if more and _open_parens(" ".join(kept)) <= 0:
            if re.fullmatch(r"\d{1,2}\)", t):
                marks.append(t[:-1])
                continue
            glued = re.fullmatch(r"(.*[가-힣A-Za-z])(\d{1,2})\)", t)
            if glued and _open_parens(glued.group(1)) <= 0:
                kept.append(glued.group(1))
                marks.append(glued.group(2))
                continue
        kept.append(t)
    texts = kept
    while texts and _is_mark(texts[-1]) and not (texts[-1].endswith(")") and _open_parens(" ".join(texts[:-1])) > 0):
        marks.insert(0, texts.pop().rstrip(")"))
    while texts and (_UNIT_RE.match(texts[-1]) or _UNIT_RE.match(texts[-1].rstrip(",/"))):   # 「ton, m3」
        unit.insert(0, texts.pop())
    if unit and texts and texts[-1] in _MULTIPLIER:        # 「천 톤」처럼 배수와 단위가 갈린 경우
        unit.insert(0, texts.pop())
    if texts and all(_is_mark(t) for t in texts):          # 「3) ton/」 — 단위 앞에 표지만 남으면 이름이 아니다
        marks = [t.rstrip(")") for t in texts] + marks
        texts = []
    label = " ".join(texts)
    m = _TRAILING_FOOT_RE.search(label)
    while m and m.start() > 0:
        head = label[:m.start()]
        if m.group(0).endswith(")") and _open_parens(head) > 0 and not re.search(r"\d\)\s*,", m.group(0)):
            # 「(Scope 1)」의 「1)」 — 괄호를 닫는다. 다만 「사용량(Scope 1)2)」처럼 뒤에 표지가 또 붙으면 그 표지만 뗀다
            tail = re.match(r"^(.*\))(\d{1,2}\))$", label)
            if tail and _open_parens(tail.group(1)) == 0:
                marks = [tail.group(2).rstrip(")")] + marks
                label = tail.group(1)
            break
        marks = re.findall(r"\d{1,2}", m.group(0)) + marks
        label = head.rstrip()
        m = _TRAILING_FOOT_RE.search(label)
    return label.strip(), " ".join(unit), marks


# ── 쪽 → 표 ────────────────────────────────────────────────────────────────────
@dataclass
class _Head:
    line: int                     # 연도 머리가 있는 (가장 아래) 줄 번호 — 몸통은 이 아래부터
    years: list[dict]             # 연도 글자(왼쪽→오른쪽)
    first_line: int = -1          # 두 줄로 갈린 머리면 위쪽 줄 — 상위 머리는 이 위에서 찾는다

    def __post_init__(self) -> None:
        if self.first_line < 0:
            self.first_line = self.line

    @property
    def x0(self) -> float:
        return self.years[0]["x0"]

    @property
    def x1(self) -> float:
        return self.years[-1]["x1"]


def _heads(lines: list[list[dict]]) -> list[_Head]:
    """쪽의 연도 머리 묶음들. 같은 줄의 옆 표 값이 있어도, 자기 구간에 값이 없으면 머리다."""
    found: list[_Head] = []
    for i, ln in enumerate(lines):
        header_marked = any(w["text"] in _HEADER_WORDS for w in ln)
        for group in _split_year_groups(ln):
            # 연도가 하나뿐인 머리(「구분 단위 2025」 — 윤리교육 이수율(2025년), SK하이닉스 p115)는 「구분·단위」 같은 머리
            # 낱말이 같은 줄에 있을 때만 받는다. 안 받으면 위 표에 붙어 제목이 틀린다.
            if len(group) < 2 and not header_marked:
                continue
            lo, hi = group[0]["x0"] - 40, group[-1]["x1"] + 10
            if any(_is_value(w["text"]) and not _is_mark(w["text"]) and lo <= w["x0"] and w["x1"] <= hi for w in ln):
                continue
            found.append(_Head(line=i, years=group))
    # 위아래 두 줄로 갈린 연도 머리(삼성생명 p131: 2024 2025 가 한 줄 위, 2022 2023 이 아래)를 잇는다.
    merged: list[_Head] = []
    for h in sorted(found, key=lambda h: (h.line, h.x0)):
        prev = next((m for m in merged if 0 < h.line - m.line <= 2 and _continues(m, h)), None)
        if prev is None:
            merged.append(h)
        else:
            prev.years = sorted(prev.years + h.years, key=lambda w: w["x0"])
            prev.line = h.line
    return merged


def _merge_same_line(lines: list[list[dict]], heads: list[_Head]) -> list[_Head]:
    """같은 줄에서 해가 되돌아가 갈린 묶음(2023 2024 2025 | 2023 2024 2025)이라도, 그 사이 아래에 **행 이름이
    없으면** 한 표의 열 묶음이다 — 회사별(HD한국조선해양·HD현대중공업·HD현대삼호)·합병 전후 열. 사이에 행 이름이
    있어야 좌우로 붙은 두 표다(삼성전자 p72)."""
    out: list[_Head] = []
    for h in sorted(heads, key=lambda h: (h.line, h.x0)):
        prev = out[-1] if out else None
        if prev is not None and prev.line == h.line and prev.first_line == h.first_line \
                and not _label_x0s(lines, h.line + 1, h.line + 16, prev.x1, h.x0):
            prev.years = prev.years + h.years
        else:
            out.append(h)
    return out


def _continues(a: _Head, b: _Head) -> bool:
    """두 머리 묶음이 한 표의 이어진 연도인가 — 가로로 맞닿고 해가 이어진다."""
    spacing = 60.0
    left, right = (a, b) if a.x0 < b.x0 else (b, a)
    years_left = [_year(w["text"]) for w in left.years]
    years_right = [_year(w["text"]) for w in right.years]
    return (0 <= right.x0 - left.x1 <= spacing * 2.5
            and max(years_left) < min(years_right))  # type: ignore[type-var]


def parse_page(words: list[dict], page: int) -> list[Table]:
    """한 쪽의 수치 표들(후보). 표를 못 세운 쪽은 빈 목록 — 「표가 없다」가 아니라 「이 방법으로 못 풀었다」."""
    # 굵게 흉내 낸 겹글자 장식(「EESSGG FFAACCTT BBOOOOKK」, 한화오션 쪽 옆 목차)은 글이 아니다
    words = [w for w in words if not _DOUBLED_RE.search(w["text"])]
    lines = [_merge_subscripts(ln) for ln in _lines(words)]
    heads = _merge_same_line(lines, _heads(lines))
    extent = {id(h): (h.first_line, next((o.line for o in sorted(heads, key=lambda o: o.line)
                                         if o.line > h.line and o.x0 < h.x1 and o.x1 > h.x0), len(lines)))
              for h in heads}
    tables: list[Table] = []
    for h in heads:
        left, right = _bounds(lines, heads, h, extent)
        end = next((o.line for o in sorted(heads, key=lambda o: o.line)
                    if o.line > h.line and o.x0 < right and o.x1 > left), len(lines))
        table = _parse_block(lines, h, end, left, right, page)
        if table is not None:
            tables.append(table)
    return tables


def _label_x0s(lines: list[list[dict]], lo_line: int, hi_line: int, x_from: float, x_to: float,
               skip: set[int] | frozenset[int] = frozenset()) -> list[float]:
    """가로 구간 (x_from, x_to) 에서 옆 표의 **행 이름이 시작하는 자리**.

    행 이름으로 보는 조건: 앞 낱말과 떨어져 있고(열 사이 틈), 같은 줄 오른쪽에 값이 **둘 이상** 이어진다. 표 아래
    각주 문단의 「2 025년」, 쪽 바닥글의 쪽 번호(「… Appendix 72」)는 값이 하나라 행으로 보지 않는다(삼성전자 p72).
    """
    out: list[float] = []
    for n, ln in enumerate(lines[max(0, lo_line):hi_line], start=max(0, lo_line)):
        if n in skip:
            continue
        for i, w in enumerate(ln):
            if not (x_from < w["x0"] < x_to) or not _LETTER.search(w["text"]) or _UNIT_RE.match(w["text"]):
                continue
            gap = w["x0"] - ln[i - 1]["x1"] if i > 0 else 99.0
            if gap >= 8 and sum(1 for v in ln[i + 1:] if _is_value(v["text"]) and v["x0"] > w["x1"]) >= 2:
                out.append(w["x0"])
    return out


def _bounds(lines: list[list[dict]], heads: list[_Head], h: _Head,
            extent: dict[int, tuple[int, int]]) -> tuple[float, float]:
    """이 표의 가로 범위. 옆 표 — 차지하는 **세로 범위가 겹치는** 머리 묶음 — 와의 경계는 그 사이에서 행 이름이
    시작하는 곳 바로 앞이다. 머리끼리 가까운지만 보면 안 된다: 삼성생명 p131 오른쪽 아래 표는 머리가 왼쪽 표
    머리보다 한참 아래라 이웃으로 못 보고 왼쪽 표의 행 이름을 제 것으로 가져왔다(2026-09-24)."""
    lo, hi = extent[id(h)]
    near = [o for o in heads if o is not h and extent[id(o)][0] < hi and extent[id(o)][1] > lo
            and _has_values_below(lines, o, extent[id(o)][1])]
    left_n = max((o for o in near if o.x1 < h.x0), key=lambda o: o.x1, default=None)
    right_n = min((o for o in near if o.x0 > h.x1), key=lambda o: o.x0, default=None)
    window = (lo, hi)
    # 표 머리 영역(연도 줄과 그 아래 두 줄)은 건너뛴다 — 옆 표의 첫 행과 같은 높이에 놓인 이 표의 하위 머리
    # (「국내 해외 전사(연결)」)를 옆 표 행 이름으로 읽으면 이 표의 마지막 열을 잘라 낸다(LG에너지솔루션 p141).
    def header_zone(o: _Head) -> set[int]:
        zone = set(range(o.first_line, o.line + 1))
        for i in range(o.line + 1, min(o.line + 4, len(lines))):
            if any(_is_value(w["text"]) and o.x0 - 40 <= w["x0"] and w["x1"] <= o.x1 + 10 for w in lines[i]):
                break                                      # 제 열 아래 값이 나오면 몸통이다 — 첫 행을 건너뛰지 않는다
            zone.add(i)
        return zone

    skip = set().union(*(header_zone(o) for o in heads)) if heads else set()
    left, right = 0.0, float("inf")
    if left_n is not None:
        cand = _label_x0s(lines, window[0], window[1], left_n.x1, h.x0, skip)
        left = min(cand) - 0.5 if cand else (left_n.x1 + h.x0) / 2
    if right_n is not None:
        cand = _label_x0s(lines, window[0], window[1], h.x1, right_n.x0, skip)
        right = min(cand) - 0.5 if cand else (h.x1 + right_n.x0) / 2
    return left, right


def _has_values_below(lines: list[list[dict]], h: _Head, end: int) -> bool:
    """머리 아래 몇 줄 안에 제 열 밑 값이 있나 — 없으면 표 머리가 아니라 연도를 늘어놓은 글이다(첫 행이 값 하나뿐인
    표도 있어 하나로 본다 — LG에너지솔루션 2024 p120 오른쪽 표의 「상수도 25,005」).

    쪽 아래 각주 「(2021, 2022, 2023)」을 머리로 보고 옆 표 경계로 쓰면 왼쪽 표의 행 이름 열이 통째로 잘렸다
    (LG에너지솔루션 2024 p120 — 왼쪽 표 37행이 전부 「이름 없음」).
    """
    for ln in lines[h.line + 1:min(end, h.line + 8)]:
        # 숫자는 오른쪽 정렬이라 연도 글자보다 20pt 가까이 오른쪽으로 나간다(LG에너지솔루션 2024 p120)
        if any(_is_value(w["text"]) and h.x0 - 40 <= w["x0"] and w["x1"] <= h.x1 + 40 for w in ln):
            return True
    return False


def _inside(w: dict, left: float, right: float) -> bool:
    """경계는 옆 표 행 이름의 시작점이다 — 이 표의 마지막 열 숫자는 그 바로 앞(간격 1~2pt)에서 끝나기도 한다."""
    return left <= w["x0"] and w["x1"] <= right


def _parse_block(lines: list[list[dict]], h: _Head, end: int, left: float, right: float,
                 page: int) -> Table | None:
    first_year_x0 = h.x0
    def in_block(ln: list[dict]) -> list[dict]:
        inside = [w for w in ln if _inside(w, left, right)]
        # 왼쪽 경계는 「값이 붙은 행 이름」이 시작하는 곳이라, 그보다 조금 앞에서 시작하는 이름만 있는 줄
        # (「용수 총 취수 원단위」 — LG에너지솔루션 2024 p120)은 앞머리가 잘린다. 경계 안 글자에 낱말 간격으로
        # 붙어 이어지는 글자는 가져온다(열 사이 틈은 8pt 이상이다).
        if inside and _LETTER.search(inside[0]["text"]):
            ahead = inside[0]
            for w in sorted((o for o in ln if o["x1"] <= ahead["x0"] and o["x0"] < left), key=lambda o: -o["x0"]):
                if ahead["x0"] - w["x1"] >= 5 or not _LETTER.search(w["text"]):
                    break
                inside.insert(0, w)
                ahead = w
        return inside
    # 값 구역의 왼쪽 끝 — 연도 머리는 여러 열 위 가운데에 놓이므로(국내·해외·전사 위의 「2023년」) 첫 열은
    # 연도 글자보다 한참 왼쪽에 있다. 머리 아래 몇 줄의 값에서 잡는다.
    near_values = [w["x0"] for ln in lines[h.line + 1:min(end, h.line + 12)]
                   if sum(1 for v in in_block(ln) if _is_value(v["text"])) >= 2
                   for w in in_block(ln) if _is_value(w["text"]) and w["x1"] >= first_year_x0 - 150]
    area_left = min(min(near_values, default=first_year_x0), first_year_x0) - 12

    # 머리 아래: 「구분 단위」처럼 왼쪽에만 글자가 있는 줄은 건너뛰고, 열 위에 글자가 있는 줄을 하위 머리로(최대 둘).
    sub_lines: list[list[dict]] = []
    k = h.line + 1
    skipped = 0
    while k < end:
        ln = in_block(lines[k])
        over_cols = [w for w in ln if w["x0"] >= area_left]
        has_value = any(_is_value(w["text"]) for w in over_cols)
        if ln and not has_value and over_cols and all(_is_mark(w["text"]) for w in over_cols):
            k += 1
            continue
        if ln and not has_value and over_cols and len(sub_lines) < 4:
            sub_lines.append(over_cols)
            k += 1
            continue
        if ln and not has_value and not over_cols and skipped < 2 and not sub_lines:
            # 바로 아래(12pt 안) 첫 값 줄에 이름이 없으면 이 줄이 그 행의 이름일 수 있다 — 건너뛰지 않고 몸통에 둔다
            nxt = in_block(lines[k + 1]) if k + 1 < end else []
            if nxt and not any(w["text"] in _HEADER_WORDS for w in ln) \
                    and any(_is_value(w["text"]) and w["x0"] >= area_left for w in nxt) \
                    and min(w["top"] for w in nxt) - min(w["top"] for w in ln) <= _ADJ_MAX_GAP \
                    and not any(_LETTER.search(w["text"]) and w["x0"] < area_left and not _UNIT_RE.match(w["text"])
                                for w in nxt):
                break
            skipped += 1
            k += 1
            continue
        break
    body_start = k
    # 연도 줄 바로 위, 열 위에 놓인 짧은 글자 덩어리 둘 이상(DX부문 DS부문 · 국내 해외)만 상위 머리로 본다.
    sup_lines: list[list[dict]] = []
    # 연도 줄 위로 세 줄까지, 열 위에 놓인 짧은 글자 덩어리(회사명 · 합병 이전/이후 · DX부문 DS부문)를 상위 머리로.
    # 긴 문장·값이 있는 줄을 만나면 멈춘다 — 표 위 서술을 머리로 잡지 않게(HD현대중공업 p158 은 세 겹이다).
    year_top = min(w["top"] for w in h.years)
    last_top = year_top
    for j in range(h.first_line - 1, max(-1, h.first_line - 4), -1):
        ln = [w for w in in_block(lines[j]) if w["x0"] >= area_left]
        if not ln:
            continue
        top = min(w["top"] for w in ln)
        # 표 머리는 연도 줄에 붙어 있다 — 멀리 떨어진 줄은 쪽 위 목차·탭(「경제 환경 사회」, SK하이닉스 p116)이다
        if year_top - top > 45 or last_top - top > 16:
            break
        last_top = top
        phrases = _phrases(ln)
        if any(_is_value(w["text"]) or _year(w["text"]) for w in ln) or any(len(p["text"]) > 18 for p in phrases):
            break
        sup_lines.insert(0, ln)

    # 몸통: 값 줄 · 라벨만 있는 줄 · 각주 문단(「1) …」 로 시작하고 값이 없는 줄부터)
    body: list[list[dict]] = []
    footnotes: dict[str, str] = {}
    in_notes = False
    seen_values = False
    for ln in lines[body_start:end]:
        ln = in_block(ln)
        if not ln:
            continue
        text = " ".join(w["text"] for w in ln)
        seen_values = seen_values or any(_is_value(w["text"]) and w["x0"] >= area_left for w in ln)
        # 각주 문단은 표지 뒤에 글이 있다(「1) 삼성생명 소유 사업장…」). 표지만 홀로 있는 줄은 위첨자로 떨어져 나온
        # 행 이름의 표지다 — 이걸 각주 시작으로 읽으면 표 몸통 전체를 각주로 삼킨다(삼성생명 p131).
        # 표지 뒤 글은 바로 붙어 있어야 한다 — 멀리 떨어진 글은 같은 높이의 쪽 옆 목차다(「2) … ESG Data」, 250pt 떨어짐
        # — 삼성생명 p138 에서 아래 표 몸통 전체를 각주로 삼켰다).
        is_note = bool(re.match(r"^(?:\d{1,2}\)|\*{1,3}|※)", ln[0]["text"])) and \
            len(re.sub(r"\s", "", text)) >= 6 and \
            (len(ln) == 1 or ln[1]["x0"] - ln[0]["x1"] <= 20) and \
            not any(_is_value(w["text"]) and w["x0"] >= area_left for w in ln[1:])
        if not is_note and not in_notes and all(_is_mark(w["text"]) for w in ln):
            continue
        if is_note or in_notes:
            in_notes = True
            m = re.match(r"^(\d{1,2})\)\s*(.*)$", text)
            if m:
                footnotes[m.group(1)] = m.group(2)
            elif footnotes:
                last = list(footnotes)[-1]
                footnotes[last] += " " + text
            continue
        body.append(ln)

    value_words = [w for ln in body for w in ln if _is_value(w["text"]) and w["x0"] >= area_left]
    if not value_words:
        return None
    numeric_lines = sum(1 for ln in body if any(w in value_words for w in ln))
    anchor, clusters = _best_alignment(value_words, numeric_lines)
    if not clusters:
        return None
    # 값이 시작된 뒤, 값이 없는데 **값 열 바로 위에** 글자가 놓인 줄 = 아래에 붙은 다른 표의 머리다(연도 없는 표 —
    # 「교육 대상 · 주기 · 인원」). 여기서 끊지 않으면 그 표의 인원 수가 이 표의 2023 열 값이 된다(삼성SDI p83 —
    # 검사를 통과한 채로). 왼쪽 분류 줄(「[수질오염물질 배출량]」)이나 옆 제목은 열 위가 아니라 끊지 않는다.
    centers = [statistics.median(_center(w) for w in value_words if abs(anchor(w) - statistics.median(c)) <= _COL_TOL)
               for c in clusters]
    started = False
    for i, ln in enumerate(body):
        if any(_is_value(w["text"]) and w["x0"] >= area_left for w in ln):
            started = True
            continue
        if started and any(_LETTER.search(w["text"]) and not _is_mark(w["text"]) and len(w["text"]) >= 2
                           and any(abs(_center(w) - cx) <= 12 for cx in centers) for w in ln):
            body = body[:i]
            value_words = [w for ln2 in body for w in ln2 if _is_value(w["text"]) and w["x0"] >= area_left]
            numeric_lines = sum(1 for ln2 in body if any(w in value_words for w in ln2))
            anchor, clusters = _best_alignment(value_words, numeric_lines)
            if not clusters:
                return None
            break
    table_right = max(max(w["x1"] for w in value_words if abs(anchor(w) - statistics.median(c)) <= _COL_TOL)
                      for c in clusters) + 3                           # 그 오른쪽 글자는 비고·옆 목차 — 표 밖
    sub_lines = [[w for w in ln if w["x0"] <= table_right] for ln in sub_lines]
    sup_lines = [[w for w in ln if w["x0"] <= table_right] for ln in sup_lines]
    header_words = [w for i in range(h.first_line, h.line + 1) for w in in_block(lines[i])]
    # 쪽 옆 목차(「Gov」「Soc」, 현대자동차 p139)는 행 이름에 섞여 나올 수 있다 — 자르지 않는다. 자르는 규칙을 두 번
    # 시험했는데 두 번 다 진짜 행 이름을 잘랐다(「Scope 1 배출량」→「1 배출량」, 「합계」 통째로). 덧붙은 낱말은 읽는
    # 쪽이 걸러낼 수 있지만 사라진 이름은 되돌릴 수 없다.
    body = [[w for w in ln if w["x0"] <= table_right] for ln in body]
    body = [ln for ln in body if ln]
    columns, notes = _columns(clusters, value_words, h, sub_lines, sup_lines, anchor, header_words)
    header_problems = _header_problems(columns)

    title = ""
    for i in range(h.first_line, max(-1, h.first_line - 4), -1):      # 머리 줄 왼쪽, 없으면 위로 세 줄까지
        cand = " ".join(w["text"] for w in in_block(lines[i]) if w["x1"] <= first_year_x0 - 2
                        and w["text"] not in ("구분", "단위", "지표", "지표명", "항목")).strip()
        # 쪽 목차·탭(대문자 영문만)·굵게 흉내 낸 겹글자(「EESSGG」)는 제목이 아니다
        if cand and re.search(r"[가-힣]", cand) and len(cand) <= 60 and not re.search(r"([A-Z])\1([A-Z])\2", cand):
            title = _strip_marks(cand)
            break

    if notes:
        title = " · ".join([title] + [n for n in notes if n not in title]) if title else " · ".join(notes)
    table = Table(page=page, title=title, columns=columns, footnotes=footnotes, header_problems=header_problems)
    value_left = min(min(w["x0"] for w in value_words if abs(anchor(w) - c.right) <= _COL_TOL) for c in columns) - 5
    rows = [_row(ln, columns, value_left, header_problems, anchor) for ln in body]
    _attach_adjacent_labels(body, rows, value_left)
    _attach_parents(body, rows, value_left)
    table.rows = [r for r in rows if r is not None]
    return table if table.rows else None


_ANCHORS = {"right": lambda w: w["x1"], "center": _center, "left": lambda w: w["x0"]}


def _best_alignment(value_words: list[dict], numeric_lines: int):
    """숫자 열이 오른쪽 정렬인지 가운데 정렬인지(SK 는 가운데) 값이 가장 잘 모이는 쪽으로 고른다.
    점수 = 버팀 있는 열에 들어간 값 수 − 열 수(열을 쪼갤수록 손해). 같으면 오른쪽 정렬."""
    best = None
    for name in ("right", "center", "left"):
        anchor = _ANCHORS[name]
        clusters = [c for c in _cluster([anchor(w) for w in value_words], _COL_TOL)
                    if len(c) >= max(2, 0.25 * numeric_lines)]
        score = sum(len(c) for c in clusters) - len(clusters)
        if best is None or score > best[0]:
            best = (score, anchor, clusters)
    return (best[1], best[2]) if best else (_ANCHORS["right"], [])


def _year_qualifiers(h: _Head, header_words: list[dict]) -> dict[int, str]:
    """연도 글자 바로 뒤에 붙은 말 — 「2025 목표」「2024 성과」「2030 목표」. 같은 해 두 열(실적·목표)을 가른다
    (하나금융지주 p196: 「2022 2023 2024 2025 2025 목표」)."""
    out: dict[int, str] = {}
    for idx, y in enumerate(h.years):
        after = sorted((w for w in header_words if abs(w["top"] - y["top"]) <= _LINE_TOL and w["x0"] > y["x1"]
                        and w["x0"] - y["x1"] <= 8), key=lambda w: w["x0"])
        if after and _LETTER.search(after[0]["text"]) and not _year(after[0]["text"]) \
                and after[0]["text"].strip("()") not in ("년", "년도", "연도", "기준"):     # 「2021」「년」 으로 갈린 글자
            out[idx] = re.sub(r"\d\)|[¹²³⁴⁵⁶⁷⁸⁹*]+$", "", after[0]["text"]).strip()
    return out


def _columns(clusters: list[list[float]], value_words: list[dict], h: _Head,
             sub_lines: list[list[dict]], sup_lines: list[list[dict]], anchor=_ANCHORS["right"],
             header_words: list[dict] | None = None) -> list[Column]:
    col_right = [statistics.median(c) for c in clusters]              # 정렬 기준점(오른쪽 끝·가운데·왼쪽 끝)
    col_center = []
    for r in col_right:
        members = [w for w in value_words if abs(anchor(w) - r) <= _COL_TOL]
        col_center.append(statistics.median(_center(w) for w in members) if members else r)
    year_marks = [(_center(w), _year(w["text"])) for w in h.years]
    spacing = min((b[0] - a[0] for a, b in zip(year_marks, year_marks[1:]) if b[0] > a[0]), default=80.0)

    def labels_per_column(lines: list[list[dict]], tol: float, drop: tuple[str, ...]) -> list[list[str]]:
        """머리 줄의 낱말을 **하나씩** 가장 가까운 열에 붙이고, 한 열에 붙은 낱말을 이어 그 열의 머리로 삼는다.
        덩어리로 먼저 묶으면 「국내 해외」처럼 한 칸 띄운 두 열 머리가 한 덩어리가 되어 두 열이 같은 이름을 받는다."""
        out: list[list[str]] = []
        for ln in lines:
            per_col: list[list[str]] = [[] for _ in col_center]
            pieces: list[dict] = []
            for p in _phrases(ln):
                covered = [cx for cx in col_center if p["x0"] - 2 <= cx <= p["x1"] + 2]
                pieces += p["words"] if len(covered) >= 2 else [p]   # 두 열에 걸친 덩어리는 낱말로 되돌린다
            for w in pieces:
                if not _LETTER.search(w["text"]) or _UNIT_RE.match(w["text"]) or w["text"] in drop \
                        or _UNIT_NOTE_RE.match(w["text"]):
                    continue
                d, idx = min((abs(_center(w) - cx), i) for i, cx in enumerate(col_center))
                if d <= tol:
                    per_col[idx].append(w["text"])
            out.append([_strip_marks(" ".join(ws)) for ws in per_col])
        return out

    qual = _year_qualifiers(h, header_words or [])
    years: list[str | None] = []
    quals: list[str] = []
    for cx in col_center:
        idx = min(range(len(year_marks)), key=lambda i: abs(year_marks[i][0] - cx))
        ok = abs(year_marks[idx][0] - cx) <= max(spacing * 0.75, 30)
        years.append(year_marks[idx][1] if ok else None)
        quals.append(qual.get(idx, "") if ok else "")
    # 연도 묶음 — 해가 되돌아가면(2025 → 2023) 새 묶음. 회사명·「합병 이전/이후」 같은 상위 머리는 묶음 위에 놓인다.
    group: list[int] = []
    for i, y in enumerate(years):
        prev = next((years[j] for j in range(i - 1, -1, -1) if years[j]), None)
        group.append((group[-1] + 1) if group and y and prev and y < prev else (group[-1] if group else 0))
    spans: dict[int, tuple[float, float]] = {}
    for g, cx in zip(group, col_center):
        lo, hi = spans.get(g, (cx, cx))
        spans[g] = (min(lo, cx), max(hi, cx))
    half = spacing / 2

    notes: list[str] = []

    def sup_labels(lines: list[list[dict]]) -> list[list[str]]:
        """상위 머리 줄 — 덩어리가 열 수만큼 많으면 열마다, 적으면 연도 묶음마다 붙인다. 두 묶음 사이 틈에 놓인
        머리(HD현대중공업 — 합병 이전·이후 두 묶음 위 가운데)는 양쪽 묶음 모두에 붙인다."""
        kept: list[list[dict]] = []
        for ln in lines:
            phrases = [p for p in _phrases(ln) if _LETTER.search(p["text"])]
            # 덩어리 하나가 표 전체에 대한 말인 것은 연도 묶음이 하나이거나 괄호 글(「(목표관리제 기준)」)일 때다.
            # 묶음이 여럿인 표의 외톨이 덩어리는 묶음 머리다(HD현대중공업 — 합병 이전·이후 두 묶음 위).
            if len(phrases) == 1 and len(col_center) >= 2 and (len(spans) < 2 or phrases[0]["text"].startswith("(")):
                notes.append(phrases[0]["text"])        # 표 전체에 대한 말 — 열 하나의 머리로 삼지 않는다
            elif phrases:
                kept.append(ln)
        lines = kept
        if len(spans) < 2:
            return labels_per_column(lines, max(spacing, 40), ())
        out: list[list[str]] = []
        for ln in lines:
            phrases = [p for p in _phrases(ln) if _LETTER.search(p["text"]) and not _UNIT_NOTE_RE.match(p["text"])]
            if len(phrases) >= 0.6 * len(col_center):
                out += labels_per_column([ln], max(spacing, 40), ())
                continue
            per_group: dict[int, list[str]] = {}
            ordered = sorted(spans.items())
            for p in phrases:
                c = _center(p)
                hit = [g for g, (lo, hi) in ordered if lo - half <= c <= hi + half]
                if not hit:
                    gaps = [(g1, g2) for (g1, (_, hi1)), (g2, (lo2, _)) in zip(ordered, ordered[1:]) if hi1 < c < lo2]
                    hit = list(gaps[0]) if gaps else [min(ordered, key=lambda it: min(abs(it[1][0] - c), abs(it[1][1] - c)))[0]]
                elif len(hit) == 1:
                    # 두 묶음 경계 가까이 놓인 머리(「HD현대중공업」 — 합병 이전·이후 위 가운데)는 양쪽 묶음 모두의 머리다
                    g = hit[0]
                    idx = [k for k, _ in ordered].index(g)
                    mid = (spans[g][0] + spans[g][1]) / 2
                    for n in (idx - 1, idx + 1):
                        if 0 <= n < len(ordered):
                            other = ordered[n][0]
                            edge = (spans[g][1] + spans[other][0]) / 2 if n > idx else (spans[other][1] + spans[g][0]) / 2
                            if abs(c - edge) < abs(c - mid):
                                hit.append(other)
                for g in hit:
                    per_group.setdefault(g, []).append(p["text"])
            out.append([_strip_marks(" ".join(per_group.get(g, []))) for g in group])
        return out

    sub = labels_per_column(sub_lines, max(spacing * 0.6, 25), ("단위", "구분", "지표", "년", "년도", "연도"))
    sup = sup_labels(sup_lines)
    columns: list[Column] = []
    for i, (r, year) in enumerate(zip(col_right, years)):
        path = [line[i] for line in sup if line[i]] + [year or "?"] + ([quals[i]] if quals[i] else []) \
            + [line[i] for line in sub if line[i]]
        columns.append(Column(key="·".join(path), year=year, path=path, right=r))
    return columns, notes


def _header_problems(columns: list[Column]) -> list[str]:
    problems: list[str] = []
    for c in columns:
        if c.year is None:
            problems.append(f"{c.right:.0f}pt 열에 연도 머리가 없습니다")
    keys = [c.key for c in columns]
    if len(set(keys)) != len(keys):
        problems.append("열 머리가 겹칩니다(같은 이름의 열이 둘 이상)")
    # 한 해 아래 열이 여럿이면(성과·목표, 국내·해외) 모두 하위 머리가 있어야 구별된다.
    by_year: dict[str | None, list[Column]] = {}
    for c in columns:
        by_year.setdefault(c.year, []).append(c)
    for year, cols in by_year.items():
        bare = [c for c in cols if len(c.path) < 2]
        # 「2025 · 2025 목표」: 목표·계획처럼 표시된 열 옆의 표시 없는 열은 실적이다 — 그 경우만 허용한다.
        planned = [c for c in cols if c not in bare and _PLAN_RE.search(" ".join(c.path))]
        if year and len(cols) > 1 and bare and not (len(bare) == 1 and len(planned) == len(cols) - 1):
            problems.append(f"{year}년 아래 열 {len(cols)}개를 구별할 머리가 없습니다")
    return problems


def _row(ln: list[dict], columns: list[Column], value_left: float, header_problems: list[str],
         anchor=_ANCHORS["right"]) -> Row | None:
    vals = [w for w in ln if _is_value(w["text"]) and w["x0"] >= value_left - 5]
    if not vals:
        return None
    label_words = [w for w in ln if w not in vals and w["x1"] < value_left + 5]
    stray = [w for w in ln if w not in vals and w not in label_words]
    first_right = min(c.right for c in columns)
    unit_like = [w for w in stray if _UNIT_RE.match(w["text"]) and anchor(w) < first_right]
    label_words += unit_like
    stray = [w for w in stray if w not in unit_like and not _is_mark(w["text"])]
    label, unit, marks = _split_label([w["text"] for w in label_words])
    values: dict[str, str] = {}
    problems: list[str] = list(header_problems)
    # 값에 붙은 작은 글씨 표지(「36⁴⁾」 — 2024년 값 재산정 각주, 삼성생명 p130)는 갈린 숫자가 아니라 그 값의 각주다.
    def small_mark(o: dict, w: dict) -> bool:
        return _is_mark(o["text"]) and (o["bottom"] - o["top"]) < 0.8 * (w["bottom"] - w["top"])
    # 갈린 숫자: 값이 다른 글자(값이든 「1,0」 같은 조각이든)와 0.8pt 안으로 붙어 있으면 한 숫자가 갈린 것이다.
    # 조각이 값 모양이 아니면 값 목록에서 빠져 「00」 만 조용히 값이 되므로 줄의 모든 글자와 대 본다.
    for w in vals:
        for o in ln:
            if o is not w and small_mark(o, w) and 0 <= o["x0"] - w["x1"] < 3:
                marks.append(o["text"].rstrip(")"))
                continue
            if o is not w and re.search(r"\d", o["text"]) and (0 <= w["x0"] - o["x1"] < _SPLIT_GAP
                                                              or 0 <= o["x0"] - w["x1"] < _SPLIT_GAP):
                problems.append(f"「{o['text']}」「{w['text']}」가 붙어 있습니다(한 숫자가 갈렸을 수 있음)")
                break
    odd = [o["text"] for o in ln if o not in vals and o["x0"] >= value_left - 5 and re.fullmatch(r"[\d,.]+", o["text"])]
    if odd:
        problems.append(f"값 자리에 숫자 모양이 어긋난 글자가 있습니다: {', '.join(odd[:3])}")
    for w in vals:
        dist, idx = min((abs(anchor(w) - c.right), i) for i, c in enumerate(columns))
        key = columns[idx].key
        if dist > _ASSIGN_TOL:
            problems.append(f"「{w['text']}」가 어느 열에도 맞지 않습니다")
        elif key in values:
            problems.append(f"「{w['text']}」와 「{values[key]}」가 같은 열({key})에 겹칩니다")
        else:
            values[key] = w["text"]
    if [w for w in stray if _LETTER.search(w["text"])]:
        problems.append("값 자리에 글자가 섞여 있습니다")
    if sum(1 for t in label.split() if re.fullmatch(r"[-−]?\d{1,3}(?:,\d{3})+(?:\.\d+)?|[-−]?\d+\.\d+", t)) >= 1:
        problems.append("행 이름에 값 같은 숫자가 섞여 있습니다(옆 표의 값일 수 있음)")
    return Row(label=label, unit=unit, marks=marks,
               indent=round(label_words[0]["x0"], 1) if label_words else 0.0,
               values=values, status="ok", problems=problems, line=" ".join(w["text"] for w in ln))


def _attach_parents(body: list[list[dict]], rows: list[Row | None], value_left: float) -> None:
    """들여쓰기가 더 깊은(8pt 이상) 행에 바로 위 얕은 행의 이름을 부모로 붙인다 — 「국내 %」 가 두 번 나오는 표
    (SK스퀘어 p102 — 자발적 이직률·전체 이직률 아래)에서 행을 가를 수 있게.

    분류 칸(병합 셀)과 항목 칸이 따로 있는 표(SK p152: 「온실가스 직접배출(Scope 1) │ 집약도(매출 …)」)는 행 이름을
    큰 틈(20pt)에서 나눠 칸마다 층으로 쌓는다 — 다음 행 「집약도(직원 1인당)」의 부모는 분류 칸 이름이 된다.
    가운데 맞춤한 분류 글자는 몇 pt 씩 어긋나므로 8pt 미만 차이는 같은 층으로 본다.

    세로로 한두 글자씩 쌓은 분류 칸(「대기/오염/물질/배출/관리」 — LG에너지솔루션 2024 p120)은 값 행 사이 아무 줄에나
    걸려 층으로 쌓으면 「관리 › 상수도」가 된다. 값 행 이름보다 8pt 넘게 왼쪽에서, 16pt 안에 같은 자리 글자가 또 있는
    이름만 있는 줄은 분류 칸 조각으로 보고 층에서 뺀다."""
    def words_of(ln: list[dict]) -> list[dict]:
        return [w for w in ln if w["x1"] < value_left + 5 and _LETTER.search(w["text"])]

    row_starts = [ws[0]["x0"] for ln, row in zip(body, rows) if row is not None and (ws := words_of(ln))]
    floor = min(row_starts, default=None)
    side = {i: (min(w["top"] for w in ws), ws[0]["x0"]) for i, (ln, row) in enumerate(zip(body, rows))
            if row is None and floor is not None and (ws := words_of(ln)) and ws[0]["x0"] < floor - 8}
    stacked = {i for i, (t, x) in side.items()
               if any(j != i and abs(t2 - t) <= 16 and abs(x2 - x) <= 10 for j, (t2, x2) in side.items())}
    stack: list[tuple[float, str]] = []                   # (들여쓰기, 이름)
    for i, (ln, row) in enumerate(zip(body, rows)):
        label_words = words_of(ln)
        if not label_words or i in stacked or (row is not None and row.label_from != "same_line"):
            continue
        segments: list[list[dict]] = [[label_words[0]]]
        for a, b in zip(label_words, label_words[1:]):
            (segments.append([b]) if b["x0"] - a["x1"] >= 20 else segments[-1].append(b))
        indent = segments[0][0]["x0"]
        while stack and stack[-1][0] >= indent - 8:
            stack.pop()
        if row is not None and stack:
            row.parent = stack[-1][1]
        for seg in segments:
            name = _split_label([w["text"] for w in seg])[0]
            if name:
                stack.append((seg[0]["x0"], name))


def _attach_adjacent_labels(body: list[list[dict]], rows: list[Row | None], value_left: float) -> None:
    """행 이름이 값 줄과 다른 줄에 있는 표 — 이름 없는 값 줄에 위·아래 「이름만 있는 줄」을 잇는다.

    실측한 모양이 넷이다(2026-09-24). 거리만으로는 못 가른다 — 현대모비스(위 7.1pt/아래 8.9pt)와 LG에너지솔루션
    2024(6.5/5.1)의 비율이 비슷한데 한쪽은 두 줄이 이름을 나눠 갖고, 한쪽은 아래 줄만 제 이름이다.
      - **단위 쌍 가운데**(현대모비스 p137 · LG에너지솔루션 2026 p141): 「TJ 값」/ 이름 /「MWh 값」 다음에 바로 다음 값
        줄 — 두 줄 모두 그 이름 줄 하나만 곁에 있다. 단위가 다르면 둘이 나눠 갖는다.
      - **값 아래**(LG에너지솔루션 2024 p120 — 한글만 숫자·영문보다 5pt 아래에 찍힌 PDF · 포스코홀딩스 p99): 값 / 이름 /
        값 / 이름 … — 줄마다 위·아래에 이름 줄이 있다. 표 끝(이름이 같은 줄에 있는 행 옆)에서부터 정해진다.
      - **두 줄로 갈린 이름**(효성중공업 p113 「총 온실가스 배출량 / (Scope 1&2)」): 앞뒤가 값 줄 위·아래에 있다.
      - **값 줄에 남은 조각**(「1」「( )」「R&D」): 한글만 내려앉아 「오창에너지플랜트 1」「기술연구원(대전)」「마곡 R&D
        캠퍼스」의 숫자·괄호·영문만 값 줄에 남는다. 가로 순서로 합친다.
    단계: ① 후보(12pt 안의 이름만 있는 줄)가 하나뿐인 줄이 그걸 갖는다 — 두 줄이 한 줄을 다투면 단위가 다를 때만
    나눠 갖고 아니면 둘 다 검사 ② 후보가 둘인 줄은 이미 쓰인 쪽을 빼고 남은 하나를 갖는다(끝에서부터 번진다)
    ③ 그래도 둘이면 두 이름 줄이 이 값 줄에만 붙어 있을 때 이어 붙이고(갈린 이름), 아니면 검사에 건다.
    붙인 행은 `label_from="adjacent_line"`. 가운데 거리만 비교하던 예전 규칙은 LG에너지솔루션 2024 에서 위 줄 이름을
    가져와 **검사를 통과한 채** 틀렸다.
    """
    def top(i: int) -> float:
        return min(w["top"] for w in body[i])

    # 글자 둘이면 이름이다(「기타」「합계」「용수」) — 셋 이상으로 두었더니 「기타」 줄을 못 봐 아래 행이 위 이름을 가져갔다
    label_only = {i for i, ln in enumerate(body) if rows[i] is None
                  and all(w["x1"] < value_left + 5 for w in ln)
                  and len(_LETTER.findall(" ".join(w["text"] for w in ln))) >= 2}

    def own_words(i: int) -> list[dict]:
        return [w for w in body[i] if w["x1"] < value_left + 5 and not _is_mark(w["text"])
                and not _UNIT_RE.match(w["text"].rstrip(",/"))]

    def fragment(i: int) -> bool:
        """값 줄의 이름이 조각인가 — 글자가 없거나(「1」「( )」), 한글 없는 짧은 영문이 옆 줄 한글 사이에 끼어 있다."""
        label = rows[i].label  # type: ignore[union-attr]
        if not label or not _LETTER.search(label):
            return True
        if _HANGUL.search(label) or len(label) > 3:
            return False
        own = own_words(i)
        if not own:
            return False
        lo, hi = min(w["x0"] for w in own), max(w["x1"] for w in own)
        for j in (i - 1, i + 1):
            if j in label_only and abs(top(j) - top(i)) <= 7:
                ws = body[j]
                if any(w["x1"] <= lo + 1 for w in ws) and any(w["x0"] >= hi - 1 for w in ws) \
                        and not any(w["x0"] < hi and w["x1"] > lo for w in ws):
                    return True
        return False

    open_rows = [i for i, r in enumerate(rows) if r is not None and fragment(i)]
    cands = {i: [j for j in (i - 1, i + 1) if j in label_only and abs(top(j) - top(i)) <= _ADJ_MAX_GAP]
             for i in open_rows}
    near = {j: [i for i in (j - 1, j + 1) if i in cands and j in cands[i]] for j in label_only}
    frags: dict[int, list[int]] = {i: [] for i in open_rows}
    doubtful: set[int] = set()
    taken: set[int] = set()

    def unit(i: int) -> str:
        return re.sub(r"\s", "", rows[i].unit)  # type: ignore[union-attr]

    # ⓪ 에너지 단위 쌍(「TJ 값 / 이름 / MWh 값」)은 사이 이름 줄을 먼저 나눠 갖는다 — 보고서가 에너지를 두 단위로
    # 나란히 싣는 관행이다. 쌍 사이에 분류 글자(「에너지원별」)가 끼면 MWh 줄이 후보를 둘 가져 쌍으로 못 보고, 그 분류
    # 글자를 제 이름으로 달았다(현대모비스 p138).
    for j in sorted(label_only):
        up, down = j - 1, j + 1
        if up in cands and down in cands and not frags[up] and not frags[down] and j in cands[up] \
                and j in cands[down] and _ENERGY_UNIT.match(unit(up)) and _ENERGY_UNIT.match(unit(down)) \
                and unit(up).lower() != unit(down).lower():
            frags[up].append(j)
            frags[down].append(j)
            taken.add(j)
    # ① 후보가 하나뿐인 줄
    wanted: dict[int, list[int]] = {}
    for i, cs in cands.items():
        if len(cs) == 1 and not frags[i]:
            wanted.setdefault(cs[0], []).append(i)
    for j, rs in wanted.items():
        if j in taken:
            doubtful.update(rs)
        elif len(rs) == 1 or (len(rs) == 2 and unit(rs[0]) and unit(rs[1]) and unit(rs[0]) != unit(rs[1])):
            for i in rs:
                frags[i].append(j)
            taken.add(j)
        else:
            doubtful.update(rs)
    # ② 끝에서부터 번지기
    changed = True
    while changed:
        changed = False
        for i, cs in cands.items():
            if frags[i] or i in doubtful or len(cs) != 2:
                continue
            rest = [j for j in cs if j not in taken]
            if len(rest) == 1:
                frags[i].append(rest[0])
                taken.add(rest[0])
                changed = True
    # ③ 두 줄로 갈린 이름
    for i, cs in cands.items():
        if frags[i] or i in doubtful or len(cs) != 2:
            continue
        if all(near[j] == [i] for j in cs):
            frags[i] = list(cs)
        else:
            doubtful.add(i)

    # 한 표 안에서 한쪽(위 또는 아래) 줄 하나만 가져간 행들은 방향이 같아야 한다. 엇갈리면(맨 위 행은 아래 줄, 맨 아래
    # 행은 위 줄) 어딘가 이름 줄 하나를 못 본 것이다 — 한 칸 밀린 이름을 검사 통과로 내보내지 않는다.
    single = {i: frags[i][0] - i for i in open_rows if len(frags[i]) == 1 and sum(frags[i][0] in frags[k] for k in open_rows) == 1}
    if len(set(single.values())) > 1:
        for i in single:
            doubtful.add(i)
    for i in open_rows:
        row = rows[i]
        assert row is not None
        if i in doubtful:
            row.problems.append("행 이름이 위·아래 두 줄 중 어느 쪽인지 알 수 없습니다")
            continue
        if not frags[i]:
            continue
        pieces = [w for j in sorted(frags[i]) for w in body[j]]
        if row.label:                                  # 값 줄에 남은 조각과 가로 순서로 합친다
            pieces = sorted(pieces + own_words(i), key=lambda w: w["x0"])
        label, extra_unit, marks = _split_label([w["text"] for w in pieces])
        label = re.sub(r"\s+\)", ")", re.sub(r"\(\s+", "(", label))
        if extra_unit and row.unit.endswith("/"):      # 「ton/」 + 다음 줄 「억원」
            row.unit += extra_unit
        row.label, row.label_from = label, "adjacent_line"
        row.marks = marks + [m for m in row.marks if m not in marks]
    for r in rows:
        if r is None:
            continue
        if not r.label:
            r.problems.append("행 이름이 없습니다")
        if r.problems:
            r.status, r.values = "check", {}
