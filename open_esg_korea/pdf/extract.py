"""PDF → 페이지 텍스트. 네트워크를 모르는 순수 함수만 둔다(그래야 fixture PDF 로 테스트가 된다).

엔진이 둘인 이유는 실측이다(삼성전자 지속가능경영보고서 2025, 87쪽 4.0MB, 2026-09-07):

| 엔진 | 전체 시간 | 숫자 깨짐 | 표 |
|---|---|---|---|
| pypdfium2 | **0.3초** | 0 | 평문 |
| pdfplumber `layout=True` | 14.2초 | 0 | **열 정렬 유지** |
| pypdf | 7.2초 | **56건**(`567 ,056`) | 평문 |

→ **훑기는 pypdfium2, 보여주기는 pdfplumber.** 전 페이지를 pdfplumber 로 뽑으면 48배 느리고,
pypdf 로 뽑으면 숫자가 깨진다(틀린 값을 보여주느니 느린 쪽이 낫다).

자간 주의: 이 문서들은 디자이너가 자간을 벌려 조판해서 **PDF 안에 진짜 공백이 박혀 있다**
(「세 계 접근 성」). 어떤 엔진을 써도 안 없어진다(pypdfium2 898 · pdfplumber 853 · pypdf 1,854건).
그래서 검색은 반드시 `squash` 로 공백을 지우고 한다 — 안 하면 「온실가스배출량」이 0쪽으로 나온다(실제로는 16쪽).
"""

from __future__ import annotations

import io
import re
from typing import Any

import pdfplumber
import pypdfium2

_WS_RE = re.compile(r"\s+")
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
#: 이 아래면 「글자가 없는 PDF」로 본다 — 스캔본·이미지 PDF. OCR 은 하지 않는다.
MIN_CHARS_PER_PAGE = 20


class PdfReadError(Exception):
    """PDF 를 열지 못했다 — 손상·암호·PDF 가 아님."""


def page_texts(data: bytes) -> list[str]:
    """전 페이지 텍스트(빠른 쪽). 「어느 쪽에 있나」를 찾는 데 쓴다."""
    try:
        doc = pypdfium2.PdfDocument(io.BytesIO(data))
    except Exception as exc:                        # pypdfium2 는 자체 예외 계층이 얕다
        raise PdfReadError(f"PDF 를 열지 못했습니다(손상되었거나 암호가 걸려 있습니다): {exc}") from exc
    try:
        return [(doc[i].get_textpage().get_text_bounded() or "") for i in range(len(doc))]
    finally:
        doc.close()


def page_layout(data: bytes, page_no: int) -> str:
    """한 쪽을 **열 정렬을 유지한 채로**. 표를 보여줄 때만 쓴다(0.18초/쪽).

    `page_no` 는 1부터 — 사람이 보는 쪽 번호와 같게 둔다.
    """
    try:
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            if not 1 <= page_no <= len(pdf.pages):
                raise PdfReadError(f"{page_no}쪽은 이 문서에 없습니다(전체 {len(pdf.pages)}쪽).")
            return compact_layout(pdf.pages[page_no - 1].extract_text(layout=True) or "")
    except PdfReadError:
        raise
    except Exception as exc:
        raise PdfReadError(f"{page_no}쪽을 읽지 못했습니다: {exc}") from exc


def page_layouts(data: bytes, page_nos: list[int]) -> dict[int, str]:
    """여러 쪽을 문서 한 번 열어 정렬 텍스트로. 못 읽은 쪽은 **빼고** 준다 — 한 쪽 때문에 전부를 버리지 않는다.

    데이터 장을 처음 받을 때 미리 떠 두는 데 쓴다(실측 2026-09-24: 10~39쪽에 0.5~1.8초).
    """
    return {p: layout for p, (layout, _words) in page_words_layouts(data, page_nos).items()}


#: 글자 윗끝을 기준선에서 글자 크기의 이만큼 위로 둔다(본문 글꼴 실측 0.70).
_ASCENT = 0.7
#: 윗끝이 기준선 위 크기의 이 비율보다 낮으면 글꼴 정보가 깨진 글자로 본다.
_BROKEN_BELOW = 0.25


def _broken_top(c: dict[str, Any]) -> float | None:
    """글꼴 정보가 깨진 글자면 기준선에서 다시 잡은 윗끝, 멀쩡하면 None.

    글꼴 정보(FontBBox)가 빠진 글꼴(주로 NotoSansCJKkr)은 pdfplumber 가 글자 상자를 기준선 **아래**에 놓아, 그 글꼴
    글자만 크기의 3/4(5pt 안팎) 아래 줄로 읽힌다. 표에서는 「행 이름이 값 아래 줄에 있는」 것처럼 보여 이름이 한 칸씩
    밀렸다(LG에너지솔루션 2024 p120 — 그림으로는 같은 줄). 시총 상위 28개 보고서 중 9건의 데이터 장이 이 글꼴을 쓴다
    (2026-09-24 실측). 글자마다 든 위치 행렬의 기준선은 맞으므로 그걸로 윗끝을 다시 계산한다. 멀쩡한 글꼴(윗끝이
    기준선 위 크기의 0.4~0.9)과 가로쓰기가 아닌 글자는 건드리지 않는다 — 모든 글자를 다시 잡으면 표 판정의 거리
    기준이 흔들려 SK p152 · 삼성SDI p75 가 풀리지 않았다.
    """
    m = c.get("matrix")
    size = c.get("size") or 0
    if not m or not size or not c.get("upright", True) or abs(m[1]) > 1e-3 or abs(m[2]) > 1e-3 or m[3] <= 0:
        return None
    if (c["y1"] - m[5]) / size >= _BROKEN_BELOW:
        return None
    return c["top"] + (c["y1"] - m[5]) - _ASCENT * size


#: 표 행 후보(`pdf/tables.py`)에 넘기는 글자 좌표. 자간 공백이 박힌 서식이라 낱말 틈 허용을 좁게 둔다.
_WORD_SETTINGS = {"x_tolerance": 1.5, "y_tolerance": 2}


def _words(page: Any) -> list[dict[str, Any]]:
    """낱말 좌표. 낱말은 원래 좌표로 묶고(위첨자 「3)」가 값에 붙어 「1,048,4853)」이 되지 않게 — 삼성SDI p75),
    글꼴 정보가 깨진 글자가 든 낱말만 **줄 높이**를 기준선에서 다시 잡는다."""
    out = []
    for w in page.extract_words(return_chars=True, **_WORD_SETTINGS):
        top, bottom = w["top"], w["bottom"]
        fixed = [_broken_top(c) for c in w["chars"]]
        if any(f is not None for f in fixed):
            tops = [c["top"] if f is None else f for f, c in zip(fixed, w["chars"])]
            top = min(tops)
            bottom = max(t + (c["bottom"] - c["top"]) for t, c in zip(tops, w["chars"]))
        text = _CONTROL_RE.sub("", w["text"])              # 글자 사이 제어문자(「30대 이상~\x07」, 삼성생명 p133)
        if not text:
            continue
        out.append({"text": text, "x0": round(w["x0"], 1), "x1": round(w["x1"], 1),
                    "top": round(top, 1), "bottom": round(bottom, 1)})
    return out


def page_words_layouts(data: bytes, page_nos: list[int]) -> dict[int, tuple[str, list[dict[str, Any]]]]:
    """여러 쪽의 (정렬 텍스트, 글자 좌표)를 문서 한 번 열어 함께 — 두 작업이 같은 글자 해석을 나눠 써서 싸다.
    못 읽은 쪽은 빼고 준다."""
    out: dict[int, tuple[str, list[dict[str, Any]]]] = {}
    try:
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            for page_no in page_nos:
                if not 1 <= page_no <= len(pdf.pages):
                    continue
                try:
                    page = pdf.pages[page_no - 1]
                    out[page_no] = (compact_layout(page.extract_text(layout=True) or ""), _words(page))
                except Exception:                      # noqa: BLE001 — 그 쪽만 빠진다. 요청 때 다시 시도한다.
                    continue
    except Exception as exc:
        raise PdfReadError(f"문서를 열어 정렬하지 못했습니다: {exc}") from exc
    return out


def compact_layout(text: str) -> str:
    """정렬 텍스트의 **빈 여백만** 걷는다 — 줄 끝 공백 · 이어진 빈 줄 · 모든 줄에 공통인 왼쪽 여백.

    줄 **안의** 칸 간격은 건드리지 않는다 — 그래야 열 정렬이 그대로 남는다. 정렬 텍스트는 쪽 너비만큼
    공백을 채워서, 수치 쪽 한 장이 6,000자를 쉽게 넘었다(30개사 실행에서 21번 잘림). 실측(2026-09-24, 3개 보고서
    데이터 장 60쪽): 쪽 글자 수 35~50% 감소, 6,000자 초과 16쪽 → 2쪽.
    """
    lines: list[str] = []
    for line in text.split("\n"):
        line = line.rstrip()
        if not line and (not lines or not lines[-1]):
            continue
        lines.append(line)
    while lines and not lines[-1]:
        lines.pop()
    indent = min((len(l) - len(l.lstrip()) for l in lines if l.strip()), default=0)
    return "\n".join(l[indent:] for l in lines)


#: 수치 쪽의 신호 — 쉼표 묶음 숫자(1,420,912)와 소수(33.7). 쪽 번호·연도 같은 맨숫자는 세지 않는다.
_DATA_NUMBER_RE = re.compile(r"(?<![\w.])\d{1,3}(?:,\d{3})+(?:\.\d+)?(?![\w])|(?<![\w.,])\d+\.\d+(?![\w])")
#: 연도 표기(2023·2023년). 수치 표는 여러 해를 나란히 싣는다 — 서로 다른 해가 둘 이상 있어야 수치 쪽으로 본다.
#: 「2023 2024 2025 가 나란히」를 요구하지 않는 이유(2026-09-24): NAVER 2025 통합보고서는 글자가 **열 단위로**
#: 나와서(2023 열의 값 전부 → 2024 열 …) 연도가 붙어 있지 않다 — 그 규칙으로는 데이터 장을 못 찾고 94쪽 한 장을 골랐다.
_YEAR_RE = re.compile(r"(?<!\d)20[12]\d(?!\d)")
DATA_PAGE_MIN_NUMBERS = 25
DATA_PAGE_MIN_YEARS = 2
#: 다음 수치 쪽이 이 쪽 수 안에 있으면 같은 장으로 잇는다 — 각주·설명 쪽 한두 장이 끼어도 끊지 않는다.
_SECTION_STEP = 3
#: 미리 떠 두는 쪽 수 상한. 실측 최대가 39쪽(현대모비스 2026)이었다 — 넘는 쪽은 요청 때 정렬한다.
DATA_SECTION_MAX_PAGES = 40


def is_data_page(text: str) -> bool:
    return (len(_DATA_NUMBER_RE.findall(text)) >= DATA_PAGE_MIN_NUMBERS
            and len(set(_YEAR_RE.findall(text))) >= DATA_PAGE_MIN_YEARS)


def data_section(pages: list[str]) -> list[int]:
    """수치 표가 모인 **데이터 장**의 쪽 번호(1부터, 연속 구간). 못 찾으면 `[]`.

    30개사 실측(2026-09-22): 원문을 연 28개 보고서 중 23개가 뒤쪽 한 장(ESG Data·Factbook·Facts & Figures·
    부록)에 수치 표를 모아 둔다 — 전체 쪽수의 66~93% 구간. 장 이름은 쓰지 않는다: 바닥글에 모든 장 이름을
    나열하는 서식이 흔해서 「Appendix」 글자는 모든 쪽에 있다. 대신 쪽마다 「쉼표·소수 숫자 25개 이상 + 서로 다른
    연도 둘 이상」을 세고, 가장 긴 연속 구간을 고른다(같으면 뒤쪽). 실측(2026-09-24, 보고서 7개 — 삼성전자·
    LG에너지솔루션·현대모비스·NAVER·삼성생명·POSCO홀딩스·신한지주): 30개사 작업에서 수치를 읽은 쪽 28개 중 27개가
    구간 안이었다. 빠진 하나(NAVER 228쪽)는 쉼표 숫자가 적은 비율 표다 — 구간 밖 쪽은 요청 때 정렬한다.

    숫자만 세면(연도 조건 없이) NAVER 의 재무제표 쪽(219–223)까지 데이터 장으로 잡힌다. 쪽 지도로 사람에게 보여줄 때
    재무제표를 「ESG 데이터」라고 부르면 틀리므로 연도 조건을 둔다.

    `[]` 는 「데이터 장이 없다」가 아니라 「이 신호로 못 찾았다」다 — 수치가 본문 장에 흩어진 보고서(2/28)와
    데이터를 별도 파일로 낸 보고서(3/28)가 있었다.
    """
    hits = [i for i, text in enumerate(pages, start=1) if is_data_page(text)]
    runs: list[list[int]] = []
    for page_no in hits:
        if runs and page_no - runs[-1][-1] <= _SECTION_STEP:
            runs[-1].append(page_no)
        else:
            runs.append([page_no])
    if not runs:
        return []
    best = max(runs, key=lambda r: (len(r), r[-1]))
    return list(range(best[0], best[-1] + 1))[:DATA_SECTION_MAX_PAGES]


#: 괘선이 없는 서식이라 선 기반 검출은 0개다(실측) — 글자 정렬로 열을 잡는다.
_TABLE_SETTINGS = {"vertical_strategy": "text", "horizontal_strategy": "text",
                   "text_x_tolerance": 2, "text_y_tolerance": 2}
_NUMBER_RE = re.compile(r"^[\d,.]+$")
_TOKEN_RE = re.compile(r"[\d][\d,.]*")


def _tidy(grid: list[list[str | None]]) -> list[list[str]]:
    """빈 행·빈 열을 걷어낸다 — 글자 정렬 전략은 빈 칸을 잔뜩 만든다."""
    rows = [[(c or "").strip() for c in row] for row in grid]
    rows = [r for r in rows if any(r)]
    if not rows:
        return []
    width = max(len(r) for r in rows)
    keep = [i for i in range(width) if any(i < len(r) and r[i] for r in rows)]
    return [[r[i] if i < len(r) else "" for i in keep] for r in rows]


def page_tables(data: bytes, page_no: int) -> list[list[list[str]]]:
    """한 쪽의 표를 격자로. **검증되지 않은 결과다** — `suspect_cells` 로 반드시 함께 확인한다."""
    try:
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            if not 1 <= page_no <= len(pdf.pages):
                raise PdfReadError(f"{page_no}쪽은 이 문서에 없습니다(전체 {len(pdf.pages)}쪽).")
            found = pdf.pages[page_no - 1].extract_tables(_TABLE_SETTINGS) or []
    except PdfReadError:
        raise
    except Exception as exc:
        raise PdfReadError(f"{page_no}쪽의 표를 읽지 못했습니다: {exc}") from exc
    return [t for t in (_tidy(g) for g in found) if t]


def suspect_cells(grid: list[list[str]], flat_text: str) -> list[tuple[int, int]]:
    """열을 잘못 잘라 **숫자가 쪼개진** 칸을 찾는다 — 실측: `307,325` 가 `3` + `07,325` 로 갈렸다.

    판별법: 격자의 숫자 칸이 평문(pypdfium2, 숫자 깨짐 0건)의 **토큰 목록에 없으면** 쪼개진 조각이다.
    고칠 수는 없지만 **어느 칸을 믿으면 안 되는지는 말해 줄 수 있다** — 조용히 틀린 값을 주는 것보다 낫다.
    """
    tokens = set(_TOKEN_RE.findall(flat_text))
    bad: list[tuple[int, int]] = []
    for r, row in enumerate(grid):
        for c, cell in enumerate(row):
            value = cell.strip()
            if value and _NUMBER_RE.match(value) and value not in tokens:
                bad.append((r, c))
    return bad


def looks_scanned(pages: list[str]) -> bool:
    """글자가 거의 없으면 스캔·이미지 PDF 다 — 「내용이 없다」가 아니라 「우리가 못 읽는다」."""
    if not pages:
        return True
    return sum(len(p.strip()) for p in pages) / len(pages) < MIN_CHARS_PER_PAGE


def squash(text: str) -> tuple[str, list[int]]:
    """공백을 지운 문자열과 «지운 문자열의 i번째 → 원문 위치» 대응표.

    발췌는 원문 표기 그대로 보여줘야 하므로 위치를 되돌릴 수 있어야 한다.
    """
    out: list[str] = []
    index: list[int] = []
    for i, ch in enumerate(text):
        if not ch.isspace():
            out.append(ch)
            index.append(i)
    return "".join(out), index


def find_in_page(text: str, query: str, *, context: int = 60) -> list[str]:
    """공백을 무시하고 찾되, 발췌는 **원문 표기 그대로** 돌려준다."""
    needle = _WS_RE.sub("", query)
    if not needle:
        return []
    flat, index = squash(text)
    snippets: list[str] = []
    start = 0
    while True:
        hit = flat.find(needle, start)
        if hit == -1:
            break
        lo = index[max(0, hit - context)]
        hi = index[min(len(index) - 1, hit + len(needle) + context)] + 1
        snippets.append(_WS_RE.sub(" ", text[lo:hi]).strip())
        start = hit + len(needle)
    return snippets


def search(pages: list[str], query: str, *, context: int = 60) -> list[dict[str, Any]]:
    """[{page(1부터), hits, snippets}] — 걸린 쪽만, 쪽 번호 순."""
    found: list[dict[str, Any]] = []
    for i, text in enumerate(pages, start=1):
        snippets = find_in_page(text, query, context=context)
        if snippets:
            found.append({"page": i, "hits": len(snippets), "snippets": snippets})
    return found
