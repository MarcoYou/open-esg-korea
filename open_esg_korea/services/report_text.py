"""지속가능경영보고서 PDF 본문 읽기 — 첨부 주소 → 내려받기 → 페이지 텍스트 → 검색·발췌.

`sustainability_reports` 가 「어떤 보고서가 있나」라면 이 도구는 「그 안에 뭐라고 썼나」다.

캐시: **PDF 바이트는 남기지 않는다**(4~80MB). 페이지 텍스트만 24시간 메모리에 둔다 —
사용자 질의 결과가 아니라 공개 공시문서의 파생 형태이고, 프로세스와 함께 사라진다(KRX 응답 캐시와 같은 성질).
문서 수와 총 글자 수 두 가지로 상한을 건다.

**수치를 자동으로 뽑지 않는다.** 표는 pdfplumber 가 열을 유지해 주지만 2단 조판 페이지에선 두 표가 섞인다 —
값이 어느 연도·어느 부문인지 프로그램이 보증할 수 없다. 정렬된 원문을 주고 판단은 넘긴다.
"""

from __future__ import annotations

import time
from typing import Any

import httpx

from open_esg_korea.krx import codes
from open_esg_korea.krx.client import KrxEsgClient, get_client
from open_esg_korea.krx.kind import KindClient, KindClientError, get_kind_client
from open_esg_korea.pdf import extract
from open_esg_korea.services.company import company_block
from open_esg_korea.services.contracts import AnalysisStatus, ToolEnvelope, source_block
from open_esg_korea.services.reports import build_sustainability_reports_payload

#: 발췌를 몇 쪽까지 실을지. 나머지는 쪽 번호만 알려 준다.
MAX_SNIPPET_PAGES = 8
MAX_SNIPPETS_PER_PAGE = 3

_TTL = 24 * 3600
_MAX_DOCS = 20
_MAX_CHARS = 5_000_000
_cache: dict[str, tuple[float, list[str]]] = {}

#: 방금 읽은 PDF **한 건만** 바이트로 잠깐 들고 있는다. 「찾기 → 그 쪽 보기」가 흔한 흐름인데
#: 쪽 정렬(pdfplumber)은 바이트가 있어야 하기 때문이다. 큰 문서는 아예 안 들고 있고(그때는 평문으로 답한다),
#: 10분이면 버린다 — 이건 캐시라기보다 한 번의 대화를 위한 임시 자리다.
_BYTES_TTL = 600
_BYTES_MAX = 25 * 1024 * 1024
_recent: tuple[str, float, bytes] | None = None


def _recent_bytes(url: str) -> bytes | None:
    if _recent and _recent[0] == url and _recent[1] > time.monotonic():
        return _recent[2]
    return None


def _keep_bytes(url: str, data: bytes) -> None:
    global _recent
    _recent = (url, time.monotonic() + _BYTES_TTL, data) if len(data) <= _BYTES_MAX else None


def cache_stats() -> dict[str, int]:
    return {"documents": len(_cache), "chars": sum(sum(len(p) for p in v[1]) for v in _cache.values())}


def clear_cache() -> None:
    global _recent
    _cache.clear()
    _recent = None


def _cached(url: str) -> list[str] | None:
    hit = _cache.get(url)
    if hit and hit[0] > time.monotonic():
        return hit[1]
    _cache.pop(url, None)
    return None


def _store(url: str, pages: list[str]) -> None:
    _cache[url] = (time.monotonic() + _TTL, pages)
    while len(_cache) > _MAX_DOCS or cache_stats()["chars"] > _MAX_CHARS:
        oldest = min(_cache, key=lambda k: _cache[k][0])
        _cache.pop(oldest, None)
        if not _cache:
            break


async def load_pages(url: str, kind: KindClient | None = None) -> list[str]:
    """첨부 PDF → 페이지 텍스트. 두 번째부터는 네트워크를 타지 않는다."""
    hit = _cached(url)
    if hit is not None:
        return hit
    data = await (kind or get_kind_client()).file(url)
    pages = extract.page_texts(data)
    _store(url, pages)
    _keep_bytes(url, data)                    # 큰 문서면 여기서 그냥 버려진다
    return pages


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


async def build_report_text_payload(company: str, *, find: str = "", page: int | None = None,
                                    table: bool = False, year: int | None = None,
                                    client: KrxEsgClient | None = None,
                                    kind: KindClient | None = None) -> dict[str, Any]:
    # 목록·자율공시 서식은 이미 있는 도구가 만든다 — 첨부 주소를 그쪽에서 받아 온다(규칙: 같은 일을 두 번 짜지 않는다).
    base = await build_sustainability_reports_payload(company, year=year, client=client, kind=kind)
    env = ToolEnvelope(tool="sustainability_report_text", status=base["status"], subject=company,
                       warnings=list(base["warnings"]), source=base["source"],
                       license=codes.KIND_LICENSE_NOTICE)
    data_in = base["data"]
    if base["status"] != AnalysisStatus.EXACT.value:
        env.data = data_in
        return env.to_dict()

    detail = data_in.get("detail") or {}
    attachment = _pick_attachment(detail.get("attachments") or [])
    out: dict[str, Any] = {"company": data_in["company"], "find": find, "page": page, "table": table,
                           "report": {k: detail.get(k) for k in ("year", "acpt_no", "report_title")},
                           "attachment": attachment}
    if attachment is None:
        env.status = AnalysisStatus.NO_DATA
        env.warnings.append("공시에 첨부된 보고서 파일이 없습니다 — 회사 사이트에만 올렸을 수 있습니다. "
                            "보고서를 안 냈다는 뜻이 아닙니다.")
        env.data = out
        return env.to_dict()

    env.source = source_block("reports", provider="KRX KIND 공시 첨부(회사 제출 PDF)",
                              page_url=attachment["url"])
    try:
        pages = await load_pages(attachment["url"], kind)
    except (KindClientError, extract.PdfReadError, httpx.HTTPError, TimeoutError) as exc:
        env.status = AnalysisStatus.NO_DATA
        env.warnings.append(f"보고서 PDF 를 읽지 못했습니다 — 내용이 없다는 뜻이 아닙니다: {exc}")
        env.data = out
        return env.to_dict()

    out["page_count"] = len(pages)
    if extract.looks_scanned(pages):
        env.status = AnalysisStatus.NO_DATA
        env.warnings.append("이미지로만 된 PDF 라 글자를 읽지 못했습니다(OCR 은 하지 않습니다) — "
                            "「내용이 없다」가 아닙니다. 원문 주소로 직접 확인하세요.")
        env.data = out
        return env.to_dict()

    if page is not None:
        out["mode"] = "page"
        if not 1 <= page <= len(pages):
            env.status = AnalysisStatus.NO_DATA
            env.warnings.append(f"{page}쪽은 이 보고서에 없습니다(전체 {len(pages)}쪽).")
            env.data = out
            return env.to_dict()
        data = _recent_bytes(attachment["url"])
        if data is None:
            # 큰 문서라 바이트를 안 들고 있다 — 80MB 를 다시 받느니 평문으로 답한다.
            out["page_text"] = pages[page - 1]
            out["aligned"] = False
            env.warnings.append("문서가 커서 열 정렬 없이 평문으로 보여줍니다(표는 한 줄로 이어집니다).")
        else:
            try:
                out["page_text"] = extract.page_layout(data, page)
                out["aligned"] = True
            except extract.PdfReadError as exc:
                out["page_text"] = pages[page - 1]
                out["aligned"] = False
                env.warnings.append(f"{page}쪽을 정렬해서 읽지 못해 평문으로 보여줍니다: {exc}")
        env.warnings.append("표는 원문 배치를 납작하게 편 것입니다 — 값이 어느 열(연도·부문)인지는 "
                            "원문 PDF 로 확인하세요. 수치를 기계적으로 뽑지 않습니다.")
        if table:
            if data is None:
                env.warnings.append("문서가 커서 격자(table=True)는 만들지 않았습니다.")
            else:
                try:
                    grids, bad = _grids(data, page, pages[page - 1])
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
