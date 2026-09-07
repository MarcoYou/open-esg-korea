"""지속가능경영보고서 PDF 본문 — 추출·검색·발췌·캐시·실패.

fixture 는 삼성전자 2025 보고서에서 **3쪽만 뽑은 진짜 PDF**(343KB)다: 표지 · 서술(자간이 벌어진 쪽) ·
Facts & Figures 수치 표. 합성 PDF 로는 한글 자간·표 문제를 재현할 수 없어 실물 일부를 쓴다.
"""

from __future__ import annotations

import pathlib

import pytest

from open_esg_korea.pdf import extract
from open_esg_korea.services.report_text import (
    build_report_text_payload, cache_stats, clear_cache, load_pages,
)
from open_esg_korea.tools.sustainability_report_text import _render

FIX = pathlib.Path(__file__).parent / "fixtures"
PDF = (FIX / "sr_005930_2025_3pages.pdf").read_bytes()
PDF_URL = ("https://kind.krx.co.kr/external/2025/06/27/000633/20250627000755/"
           "%EC%82%BC%EC%84%B1%EC%A0%84%EC%9E%90%20%EC%A7%80%EC%86%8D%EA%B0%80%EB%8A%A5"
           "%EA%B2%BD%EC%98%81%EB%B3%B4%EA%B3%A0%EC%84%9C_2025.pdf")


@pytest.fixture(autouse=True)
def _fresh_cache():
    clear_cache()
    yield
    clear_cache()


# ── 추출 계층 (네트워크 없음) ──────────────────────────────────────────────────
def test_pages_come_out_and_numbers_are_not_broken():
    """pypdf 는 `567 ,056` 처럼 숫자 안에 공백을 넣는다 — 틀린 값을 보여주면 안 되므로 이걸 지킨다."""
    pages = extract.page_texts(PDF)
    assert len(pages) == 3
    assert "567,056" in pages[2] and "567 ,056" not in pages[2]


def test_search_ignores_spacing_because_the_pdf_has_it_baked_in():
    """원문이 자간을 벌려 조판해 「재생 에너지」처럼 띄어져 있다 — 공백을 무시하지 않으면 0건이 된다."""
    pages = extract.page_texts(PDF)
    assert extract.search(pages, "재생에너지")          # 붙여 써도
    assert extract.search(pages, "재 생 에 너 지")       # 띄어 써도 같은 곳을 찾는다


def test_snippet_is_the_original_wording_not_the_squashed_one():
    hits = extract.search(extract.page_texts(PDF), "재생에너지")
    snippet = hits[0]["snippets"][0]
    assert "재생에너지 사용량" in snippet or "재생에너지 전환율" in snippet
    assert "  " not in snippet                       # 발췌는 한 줄로 정리해서 준다


def test_layout_mode_keeps_the_table_columns():
    """표를 보여줄 땐 열 정렬을 살린다 — 평문이면 어느 값이 어느 해인지 알 수 없다."""
    text = extract.page_layout(PDF, 3)
    line = next(l for l in text.split("\n") if "사업장 에너지 사용량" in l)
    assert "4,327" in line and "30,850" in line      # 같은 줄에 그 행의 값이 모여 있다


def test_missing_page_is_an_error_not_an_empty_string():
    with pytest.raises(extract.PdfReadError):
        extract.page_layout(PDF, 99)


def test_broken_bytes_are_a_read_error_not_a_crash():
    with pytest.raises(extract.PdfReadError):
        extract.page_texts(b"not a pdf at all")


def test_scanned_pdf_is_detected_as_unreadable_not_empty():
    """글자가 없는 PDF 는 「내용이 없다」가 아니라 「우리가 못 읽는다」다."""
    assert extract.looks_scanned(["", "  ", ""]) is True
    assert extract.looks_scanned(extract.page_texts(PDF)) is False


# ── 서비스·도구 ──────────────────────────────────────────────────────────────
async def test_overview_gives_the_table_of_contents(krx_client, kind_client):
    payload = await build_report_text_payload("삼성전자")
    data = payload["data"]
    assert data["mode"] == "overview" and data["page_count"] == 3
    assert "Facts & Figures" in data["toc"]
    assert data["attachment"]["name"].endswith(".pdf")


async def test_find_reports_pages_and_snippets(krx_client, kind_client):
    payload = await build_report_text_payload("삼성전자", find="재생에너지")
    data = payload["data"]
    assert data["match_pages"] == [3] and data["total_hits"] >= 2
    assert "재생에너지" in data["matches"][0]["snippets"][0]


async def test_no_hit_says_not_found_rather_than_absent(krx_client, kind_client):
    payload = await build_report_text_payload("삼성전자", find="존재하지않는표현")
    assert payload["data"]["match_pages"] == []
    assert any("「없다」고 단정하지 마세요" in w for w in payload["warnings"])


async def test_page_mode_is_aligned_and_warns_about_flattened_tables(krx_client, kind_client):
    payload = await build_report_text_payload("삼성전자", page=3)
    data = payload["data"]
    assert data["aligned"] is True
    assert "사업장 에너지 사용량" in data["page_text"]
    assert any("수치를 기계적으로 뽑지 않습니다" in w for w in payload["warnings"])


async def test_page_out_of_range_is_no_data(krx_client, kind_client):
    payload = await build_report_text_payload("삼성전자", page=99)
    assert payload["status"] == "no_data"
    assert any("99쪽은 이 보고서에 없습니다" in w for w in payload["warnings"])


async def test_second_question_does_not_hit_the_network(krx_client, kind_client):
    await build_report_text_payload("삼성전자", find="재생에너지")
    calls = kind_client.calls
    await build_report_text_payload("삼성전자", find="폐기물")
    assert kind_client.calls == calls                 # 페이지 텍스트가 캐시에 있다
    assert cache_stats()["documents"] == 1


async def test_pdf_bytes_are_not_kept_as_the_document_cache(krx_client, kind_client):
    """캐시에 남는 것은 텍스트뿐이다 — 4~80MB 짜리 원본을 들고 있지 않는다."""
    await load_pages(PDF_URL, kind_client)
    assert cache_stats()["chars"] < 100_000           # 3쪽 텍스트는 수천 자
    assert cache_stats()["documents"] == 1


async def test_company_without_an_attachment_is_no_data(krx_client, kind_client, monkeypatch):
    from open_esg_korea.services import report_text
    monkeypatch.setattr(report_text, "_pick_attachment", lambda atts: None)
    payload = await build_report_text_payload("삼성전자")
    assert payload["status"] == "no_data"
    assert any("회사 사이트에만 올렸을 수 있습니다" in w for w in payload["warnings"])


async def test_korean_attachment_wins_when_both_languages_are_filed():
    """SK하이닉스처럼 국·영문 2건이 붙는 회사가 있다 — 국문을 고른다."""
    from open_esg_korea.services.report_text import _pick_attachment
    picked = _pick_attachment([{"name": "SK hynix Sustainability Report 2025_ENG.pdf", "url": "e"},
                               {"name": "SK하이닉스 지속가능경영보고서 2025_KOR.pdf", "url": "k"}])
    assert picked["url"] == "k"


async def test_markdown_shows_snippets_and_the_source_pdf(krx_client, kind_client):
    text = _render(await build_report_text_payload("삼성전자", find="재생에너지"))
    assert "### 3쪽" in text and "재생에너지" in text
    assert "원문 PDF: [삼성전자 지속가능경영보고서_2025.pdf]" in text
    assert "공시 원문" in text                          # 평가기관 고지가 아니라 공시 고지
