"""지속가능경영보고서 PDF 본문 읽기 — 첨부 주소 → 내려받기 → 페이지 텍스트 → 검색·발췌.

`sustainability_reports` 가 「어떤 보고서가 있나」라면 이 도구는 「그 안에 뭐라고 썼나」다.

캐시: **PDF 바이트는 남기지 않는다**(4~80MB). 페이지 텍스트와 **데이터 장 쪽의 정렬 텍스트**만 24시간 메모리에
둔다 — 사용자 질의 결과가 아니라 공개 공시문서의 파생 형태이고, 프로세스와 함께 사라진다(KRX 응답 캐시와 같은
성질). 문서 수와 총 글자 수 두 가지로 상한을 건다.

동시성(2026-09-24): 여러 대화가 동시에 다른 보고서를 열어도 흔들리지 않게 두 가지를 지킨다.
  1. PDF 해석은 **스레드에서** 한다 — 이벤트 루프에서 돌리면 해석하는 동안 서버의 모든 요청이 멈춘다.
  2. 데이터 장(수치 표가 모인 뒤쪽 장)은 **처음 받을 때 정렬해 둔다** — 원본 바이트는 한 건만 잠깐 들고 있어서
     동시 호출이 서로 밀어낸다. 밀린 뒤 다른 쪽을 정렬해 달라고 하면 원본을 다시 받는다(25MB 이하).

**수치를 자동으로 뽑지 않는다.** 표는 pdfplumber 가 열을 유지해 주지만 2단 조판 페이지에선 두 표가 섞인다 —
값이 어느 연도·어느 부문인지 프로그램이 보증할 수 없다. 정렬된 원문을 주고 판단은 넘긴다.
"""

from __future__ import annotations

import asyncio
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, TypeVar

import httpx

from open_esg_korea.krx import codes
from open_esg_korea.krx.client import KrxEsgClient
from open_esg_korea.krx.kind import KindClient, KindClientError, get_kind_client
from open_esg_korea.pdf import extract
from open_esg_korea.pdf import tables as table_parser
from open_esg_korea.services.contracts import AnalysisStatus, ToolEnvelope, source_block
from open_esg_korea.services.reports import build_sustainability_reports_payload

#: 발췌를 몇 쪽까지 실을지. 나머지는 쪽 번호만 알려 준다.
MAX_SNIPPET_PAGES = 8
MAX_SNIPPETS_PER_PAGE = 3
#: 쪽 범위(`page="136-140"`)로 한 번에 보여줄 최대 쪽 수.
MAX_PAGE_SPAN = 5

_TTL = 24 * 3600
_MAX_DOCS = 20
_MAX_CHARS = 5_000_000


@dataclass
class _Doc:
    """문서 한 건의 텍스트 캐시. 원본 바이트는 없다 — 크기만 적어 둔다(다시 받을지 정할 때 쓴다)."""

    expires: float
    pages: list[str]                                           # 쪽 평문(pypdfium2) — 찾기용
    size: int                                                  # 원본 바이트 수
    section: list[int]                                         # 데이터 장 쪽 번호(1부터), 못 찾으면 []
    layouts: dict[int, str] = field(default_factory=dict)      # 쪽 번호 → 정렬 텍스트(pdfplumber)
    tables: dict[int, list[table_parser.Table]] = field(default_factory=dict)   # 쪽 번호 → 표 행 후보

    def chars(self) -> int:
        return (sum(len(p) for p in self.pages) + sum(len(t) for t in self.layouts.values())
                + sum(len(r.line) * 3 for ts in self.tables.values() for t in ts for r in t.rows))


_cache: dict[str, _Doc] = {}

#: 방금 읽은 PDF **한 건만** 바이트로 잠깐 들고 있는다. 데이터 장 밖의 쪽을 정렬하거나 격자를 만들 때
#: 쓴다. 큰 문서는 아예 안 들고 있고, 10분이면 버린다 — 캐시라기보다 한 번의 대화를 위한 임시 자리다.
_BYTES_TTL = 600
_BYTES_MAX = 25 * 1024 * 1024
_recent: tuple[str, float, bytes] | None = None

#: PDF 해석은 CPU 를 쓰는 동기 작업이다. 이벤트 루프 위에서 돌리면 해석하는 동안 서버의 **모든** 요청이
#: 기다린다(2026-09-22 30개사 동시 실행에서 5개 작업이 같은 시각에 시간 초과로 멈췄다 — 이것이 원인이라는 건
#: 추정이지만, 루프를 막는 구조였던 것은 코드상 사실이다). 그래서 스레드로 넘긴다.
#:   - `_PARSE_SLOTS`: 동시에 둘까지만 푼다 — 한 건 해석에 원본 크기의 몇 배 메모리를 쓴다.
#:   - `_PDFIUM`: pypdfium2 는 **한 번에 하나만**. PDFium 은 스레드 안전하지 않다(pypdfium2 문서
#:     「Incompatibility with Threading」). pdfplumber(pdfminer, 순수 파이썬)는 여기에 걸리지 않는다.
_PARSE_SLOTS = threading.BoundedSemaphore(2)
_PDFIUM = threading.Lock()

_T = TypeVar("_T")


async def _parse(fn: Callable[..., _T], *args: Any, pdfium: bool = False) -> _T:
    def run() -> _T:
        with _PARSE_SLOTS:
            if pdfium:
                with _PDFIUM:
                    return fn(*args)
            return fn(*args)
    return await asyncio.to_thread(run)


def _recent_bytes(url: str) -> bytes | None:
    if _recent and _recent[0] == url and _recent[1] > time.monotonic():
        return _recent[2]
    return None


def _keep_bytes(url: str, data: bytes) -> None:
    global _recent
    _recent = (url, time.monotonic() + _BYTES_TTL, data) if len(data) <= _BYTES_MAX else None


def cache_stats() -> dict[str, int]:
    return {"documents": len(_cache), "chars": sum(d.chars() for d in _cache.values()),
            "aligned_pages": sum(len(d.layouts) for d in _cache.values()),
            "table_pages": sum(len(d.tables) for d in _cache.values())}


def clear_cache() -> None:
    global _recent
    _cache.clear()
    _recent = None


def _cached(url: str) -> _Doc | None:
    doc = _cache.get(url)
    if doc and doc.expires > time.monotonic():
        return doc
    _cache.pop(url, None)
    return None


def _trim() -> None:
    while len(_cache) > _MAX_DOCS or cache_stats()["chars"] > _MAX_CHARS:
        oldest = min(_cache, key=lambda k: _cache[k].expires)
        _cache.pop(oldest, None)
        if not _cache:
            break


def _store(url: str, doc: _Doc) -> None:
    _cache[url] = doc
    _trim()


async def load_document(url: str, kind: KindClient | None = None) -> _Doc:
    """첨부 PDF → 쪽 평문 + 데이터 장 정렬 텍스트. 두 번째부터는 네트워크를 타지 않는다.

    데이터 장을 **처음 받을 때** 정렬해 두는 이유(30개사 동시 실행, 2026-09-22): 원본은 한 건만 들고 있어서
    동시 호출이 서로 밀어냈고, 쪽 보기 133회 중 100회가 평문으로 나갔다 — 문서는 크기를 확인한 21건이 모두
    25MB 이하였는데 「문서가 커서」라고 안내했다. 데이터 장을 텍스트로 떠 두면 밀려도 상관없다.
    """
    hit = _cached(url)
    if hit is not None:
        return hit
    data = await (kind or get_kind_client()).file(url)
    pages = await _parse(extract.page_texts, data, pdfium=True)
    section = [] if extract.looks_scanned(pages) else extract.data_section(pages)
    layouts: dict[int, str] = {}
    tables: dict[int, list[table_parser.Table]] = {}
    if section:
        try:
            layouts, tables = await _parse(_layouts_and_tables, data, section)
        except extract.PdfReadError:
            layouts, tables = {}, {}      # 훑기는 됐으니 찾기·평문 보기는 된다. 정렬은 요청 때 다시 시도한다.
    doc = _Doc(expires=time.monotonic() + _TTL, pages=pages, size=len(data), section=section,
               layouts=layouts, tables=tables)
    _store(url, doc)
    _keep_bytes(url, data)
    return doc


def _layouts_and_tables(data: bytes, page_nos: list[int]) -> tuple[dict[int, str], dict[int, list[table_parser.Table]]]:
    """정렬 텍스트와 표 행 후보를 한 번에(스레드 안에서). 글자 좌표는 표로 풀고 나면 버린다 — 캐시에 남기지 않는다."""
    both = extract.page_words_layouts(data, page_nos)
    return ({p: layout for p, (layout, _) in both.items()},
            {p: table_parser.parse_page(words, p) for p, (_, words) in both.items()})


async def page_tables(url: str, doc: _Doc, page_no: int,
                      kind: KindClient) -> tuple[list[table_parser.Table] | None, str]:
    """한 쪽의 표 행 후보. 데이터 장이면 캐시에서, 아니면 원본에서 풀어 캐시에 더한다. 못 풀면 (None, 이유)."""
    if page_no in doc.tables:
        return doc.tables[page_no], ""
    data, reason = await _bytes_for_alignment(url, doc, kind)
    if data is None:
        return None, reason
    try:
        layouts, tables = await _parse(_layouts_and_tables, data, [page_no])
    except extract.PdfReadError as exc:
        return None, f"{page_no}쪽을 읽지 못했습니다: {exc}"
    if page_no not in tables:
        return None, f"{page_no}쪽을 읽지 못했습니다."
    doc.layouts.update(layouts)
    doc.tables.update(tables)
    _trim()
    return tables[page_no], ""


async def load_pages(url: str, kind: KindClient | None = None) -> list[str]:
    """첨부 PDF → 페이지 텍스트. 다른 도구(온실가스 공시치 대조)가 쓰는 입구."""
    return (await load_document(url, kind)).pages


def _span(pages: list[int]) -> str:
    return f"{pages[0]}–{pages[-1]}쪽" if len(pages) > 1 else f"{pages[0]}쪽"


async def _bytes_for_alignment(url: str, doc: _Doc, kind: KindClient) -> tuple[bytes | None, str]:
    """정렬·격자(pdfplumber)에 쓸 원본. 없으면 **이유**를 함께 돌려준다 — 이유를 뭉뚱그려 말하지 않는다."""
    data = _recent_bytes(url)
    if data is not None:
        return data, ""
    if doc.size > _BYTES_MAX:
        note = f" 데이터 장({_span(doc.section)})은 처음 받을 때 정렬해 두었습니다" if doc.section else ""
        return None, (f"문서가 {doc.size / 2**20:.0f}MB 라 정렬용으로 다시 받지 않았습니다"
                      f"(상한 {_BYTES_MAX / 2**20:.0f}MB).{note}")
    try:
        data = await kind.file(url)
    except (KindClientError, httpx.HTTPError, TimeoutError) as exc:
        return None, f"정렬용 원본을 다시 받지 못했습니다: {exc}"
    _keep_bytes(url, data)
    return data, ""


async def _page_view(url: str, doc: _Doc, page_no: int, kind: KindClient) -> dict[str, Any]:
    """한 쪽 — 정렬 텍스트가 먼저, 못 주면 평문과 **그 이유**(`fallback`)."""
    text = doc.layouts.get(page_no)
    if text is not None:
        return {"page": page_no, "text": text, "aligned": True, "fallback": ""}
    data, reason = await _bytes_for_alignment(url, doc, kind)
    if data is not None:
        try:
            text = await _parse(extract.page_layout, data, page_no)
        except extract.PdfReadError as exc:
            reason = f"{page_no}쪽을 정렬해서 읽지 못했습니다: {exc}"
        else:
            doc.layouts[page_no] = text
            _trim()
            return {"page": page_no, "text": text, "aligned": True, "fallback": ""}
    return {"page": page_no, "text": doc.pages[page_no - 1], "aligned": False, "fallback": reason}


_PAGE_ARG_RE = re.compile(r"^\s*(\d+)\s*(?:[-~–]\s*(\d+))?\s*$")


def page_numbers(page: int | str) -> list[int] | str:
    """`73` · `"73"` · `"136-140"` → 쪽 번호 목록. 알아들을 수 없으면 안내 문구(str)를 돌려준다."""
    if isinstance(page, int):
        return [page]
    m = _PAGE_ARG_RE.match(str(page))
    if not m:
        return f'page 는 쪽 번호(73) 또는 범위("136-140")로 주세요 — 받은 값: {page!r}'
    lo = int(m.group(1))
    hi = int(m.group(2) or lo)
    if hi < lo:
        return f"범위의 끝({hi}쪽)이 시작({lo}쪽)보다 앞입니다."
    if hi - lo + 1 > MAX_PAGE_SPAN:
        return f"한 번에 {MAX_PAGE_SPAN}쪽까지 봅니다({lo}–{hi}쪽은 {hi - lo + 1}쪽) — 나눠서 부르세요."
    return list(range(lo, hi + 1))


def _pick_attachment(attachments: list[dict[str, str]]) -> dict[str, str] | None:
    """국문 보고서를 먼저 고른다 — SK하이닉스처럼 국·영문 2건이 붙는 회사가 있다."""
    if not attachments:
        return None
    korean = [a for a in attachments if not any(m in a["name"].upper() for m in ("_ENG", "ENG.PDF", "ENGLISH"))]
    return (korean or attachments)[0]


def _grids(data: bytes, page: int, flat: str) -> tuple[list[dict[str, Any]], int]:
    """격자 + **믿으면 안 되는 칸 표시**. 고칠 수 없으니 어디가 위험한지라도 말한다."""
    out: list[dict[str, Any]] = []
    total_bad = 0
    for grid in extract.page_tables(data, page):
        bad = extract.suspect_cells(grid, flat)
        total_bad += len(bad)
        out.append({"rows": grid, "cells": sum(len(r) for r in grid),
                    "suspect": [{"row": r, "col": c, "value": grid[r][c]} for r, c in bad]})
    return out, total_bad


@dataclass
class OpenedReport:
    """보고서 한 건을 여는 공통 단계의 결과 — `doc` 가 None 이면 `env` 가 이미 답(no_data 등)이다."""

    env: ToolEnvelope
    out: dict[str, Any]
    doc: _Doc | None = None
    url: str = ""
    kind: KindClient | None = None
    detail: dict[str, Any] = field(default_factory=dict)      # 자율공시 서식(목차 요약 등)


async def open_report(tool: str, company: str, *, year: int | None, client: KrxEsgClient | None,
                      kind: KindClient | None, out: dict[str, Any]) -> OpenedReport:
    """목록 → 첨부 고르기 → PDF 읽기 → 스캔본 판정. 본문 도구와 부록 표 도구가 같이 쓴다(같은 일을 두 번 짜지 않는다)."""
    # 목록·자율공시 서식은 이미 있는 도구가 만든다 — 첨부 주소를 그쪽에서 받아 온다.
    base = await build_sustainability_reports_payload(company, year=year, client=client, kind=kind)
    env = ToolEnvelope(tool=tool, status=base["status"], subject=company,
                       warnings=list(base["warnings"]), source=base["source"],
                       license=codes.KIND_LICENSE_NOTICE)
    data_in = base["data"]
    if base["status"] != AnalysisStatus.EXACT.value:
        env.data = data_in
        return OpenedReport(env=env, out=data_in)

    detail = data_in.get("detail") or {}
    attachment = _pick_attachment(detail.get("attachments") or [])
    out = {"company": data_in["company"], **out,
           "report": {k: detail.get(k) for k in ("year", "acpt_no", "report_title")}, "attachment": attachment}
    if attachment is None:
        env.status = AnalysisStatus.NO_DATA
        env.warnings.append("공시에 첨부된 보고서 파일이 없습니다 — 회사 사이트에만 올렸을 수 있습니다. "
                            "보고서를 안 냈다는 뜻이 아닙니다.")
        env.data = out
        return OpenedReport(env=env, out=out)

    env.source = source_block("reports", provider="KRX KIND 공시 첨부(회사 제출 PDF)",
                              page_url=attachment["url"])
    kind = kind or get_kind_client()
    url = attachment["url"]
    try:
        doc = await load_document(url, kind)
    except (KindClientError, extract.PdfReadError, httpx.HTTPError, TimeoutError) as exc:
        env.status = AnalysisStatus.NO_DATA
        env.warnings.append(f"보고서 PDF 를 읽지 못했습니다 — 내용이 없다는 뜻이 아닙니다: {exc}")
        env.data = out
        return OpenedReport(env=env, out=out)

    out["page_count"] = len(doc.pages)
    out["data_section"] = [doc.section[0], doc.section[-1]] if doc.section else None
    if extract.looks_scanned(doc.pages):
        env.status = AnalysisStatus.NO_DATA
        env.warnings.append("이미지로만 된 PDF 라 글자를 읽지 못했습니다(OCR 은 하지 않습니다) — "
                            "「내용이 없다」가 아닙니다. 원문 주소로 직접 확인하세요.")
        env.data = out
        return OpenedReport(env=env, out=out)
    return OpenedReport(env=env, out=out, doc=doc, url=url, kind=kind, detail=detail)


async def build_report_text_payload(company: str, *, find: str = "", page: int | str | None = None,
                                    table: bool = False, year: int | None = None,
                                    client: KrxEsgClient | None = None,
                                    kind: KindClient | None = None) -> dict[str, Any]:
    opened = await open_report("sustainability_report_text", company, year=year, client=client, kind=kind,
                               out={"find": find, "page": page, "table": table})
    env, out, doc = opened.env, opened.out, opened.doc
    if doc is None:
        return env.to_dict()
    url, kind, detail = opened.url, opened.kind, opened.detail
    assert kind is not None
    pages = doc.pages

    if page is not None:
        out["mode"] = "page"
        wanted = page_numbers(page)
        if isinstance(wanted, str):
            env.status = AnalysisStatus.NO_DATA
            env.warnings.append(wanted)
            env.data = out
            return env.to_dict()
        shown = [p for p in wanted if 1 <= p <= len(pages)]
        if not shown:
            env.status = AnalysisStatus.NO_DATA
            env.warnings.append(f"{_span(wanted)}은 이 보고서에 없습니다(전체 {len(pages)}쪽).")
            env.data = out
            return env.to_dict()
        if len(shown) < len(wanted):
            env.warnings.append(f"전체 {len(pages)}쪽이라 {_span(shown)}만 보여줍니다.")
        views = [await _page_view(url, doc, p, kind) for p in shown]
        out["page_views"] = views
        if len(views) == 1:                   # 한 쪽이면 예전 키도 그대로 둔다 — json 을 읽는 쪽을 깨지 않게
            out["page_text"] = views[0]["text"]
            out["aligned"] = views[0]["aligned"]
        for v in views:
            if not v["aligned"]:
                env.warnings.append(f"{v['page']}쪽은 열 정렬 없이 평문으로 보여줍니다(표는 한 줄로 이어집니다) — "
                                    f"{v['fallback']}")
        env.warnings.append("표는 원문 배치를 납작하게 편 것입니다 — 값이 어느 열(연도·부문)인지는 "
                            "원문 PDF 로 확인하세요. 수치를 기계적으로 뽑지 않습니다.")
        if table:
            if len(shown) > 1:
                env.warnings.append("격자(table=True)는 한 쪽씩만 만듭니다 — page 에 쪽 번호 하나를 주세요.")
            else:
                data, reason = await _bytes_for_alignment(url, doc, kind)
                if data is None:
                    env.warnings.append(f"격자(table=True)는 만들지 않았습니다 — {reason}")
                else:
                    try:
                        grids, bad = await _parse(_grids, data, shown[0], pages[shown[0] - 1])
                    except extract.PdfReadError as exc:
                        env.warnings.append(f"격자를 만들지 못했습니다: {exc}")
                    else:
                        out["tables"] = grids
                        out["suspect_cells"] = bad
                        env.warnings.append(
                            "격자(table=True)는 **검증되지 않은 실험 결과**입니다. 이 서식은 괘선이 없어 "
                            "글자 위치로 열을 가르는데, 한 쪽에 표가 좌우로 놓이면 행이 섞이고 숫자가 갈라집니다"
                            + (f" — 이 쪽에서 {bad}칸이 그렇게 보입니다(표시해 뒀습니다)." if bad else
                               " — 이 쪽에선 그런 칸이 잡히지 않았습니다(없다는 보장은 아닙니다).")
                            + " 값을 쓰기 전에 위 원문 배치와 대조하세요.")
    elif find:
        out["mode"] = "find"
        hits = extract.search(pages, find)
        out["match_pages"] = [h["page"] for h in hits]
        out["matches"] = [{"page": h["page"], "hits": h["hits"],
                           "snippets": h["snippets"][:MAX_SNIPPETS_PER_PAGE]}
                          for h in hits[:MAX_SNIPPET_PAGES]]
        out["total_hits"] = sum(h["hits"] for h in hits)
        if not hits:
            env.warnings.append(f"「{find}」를 찾지 못했습니다. 공백을 무시하고 이미 찾아봤습니다 — "
                                "표기가 다르거나(영문·약어) 이 보고서에 없는 내용일 수 있습니다. "
                                "「없다」고 단정하지 마세요.")
        elif len(hits) > MAX_SNIPPET_PAGES:
            env.warnings.append(f"{len(hits)}쪽에서 걸려 앞 {MAX_SNIPPET_PAGES}쪽만 발췌했습니다. "
                                "page 로 쪽을 지정하면 그 쪽 전체를 봅니다.")
    else:
        out["mode"] = "overview"
        out["toc"] = detail.get("summary", "")

    env.data = out
    env.next_actions = [
        f'sustainability_reports(company="{company}") — 연도별 목록·검증기관',
        f'sustainability_report_text(company="{company}", find="Scope 3") — 본문에서 찾기',
    ]
    return env.to_dict()
