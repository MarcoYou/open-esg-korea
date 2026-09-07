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
            return pdf.pages[page_no - 1].extract_text(layout=True) or ""
    except PdfReadError:
        raise
    except Exception as exc:
        raise PdfReadError(f"{page_no}쪽을 읽지 못했습니다: {exc}") from exc


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
