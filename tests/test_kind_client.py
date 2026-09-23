"""KIND 원문 클라이언트 — 3단 호출·캐시·서식 분기·실패.

fixture 는 2026-09-07 실호출 스냅샷이다(삼성전자 본문은 원칙 3개만 남긴 subset).
"""

from __future__ import annotations

import httpx
import pytest

from open_esg_korea.krx import codes
from open_esg_korea.krx.kind import KindClient, KindClientError, form_no, parse_body_url, parse_documents

SAMSUNG_2025 = "20250530001005"
KB_2025 = "20250305001136"


async def test_viewer_lists_main_and_attached_documents(kind_client):
    docs = await kind_client.documents(SAMSUNG_2025)
    main = [d for d in docs if d["kind"] == "main"]
    attached = [d for d in docs if d["kind"] == "attached"]
    assert [d["doc_no"] for d in main] == ["20250530001923"]      # 접수번호(…001005)와 다르다
    assert [d["doc_no"] for d in attached] == ["20250530001922"]
    assert main[0]["title"].startswith("기업지배구조 보고서 공시") and main[0]["latest"] is True


async def test_document_walks_three_hops_and_returns_the_body(kind_client):
    doc = await kind_client.document(SAMSUNG_2025)
    assert kind_client.calls == 3                                  # 뷰어 → 경로 → 본문
    assert doc["form_no"] == codes.KIND_FORM_GOV_REPORT
    assert doc["body_url"].endswith("/20250530001923/99667.htm")
    assert 'id="DetailedPrinciple_4-4"' in doc["html"]
    assert "(세부원칙 4-4)" in doc["html"]


async def test_same_acceptance_number_hits_cache_not_network(kind_client):
    await kind_client.document(SAMSUNG_2025)
    await kind_client.document(SAMSUNG_2025)
    assert kind_client.calls == 3 and kind_client.cache_hits == 1


async def test_financial_company_body_is_the_annual_report_form(kind_client):
    """금융회사는 연차보고서로 갈음한다 — 제목·서식번호 둘 다로 알 수 있고, 본문엔 세부원칙이 없다."""
    docs = await kind_client.documents(KB_2025)
    main = next(d for d in docs if d["kind"] == "main")
    assert codes.KIND_ANNUAL_REPORT_MARK in main["title"]

    doc = await kind_client.document(KB_2025)
    assert doc["form_no"] == codes.KIND_FORM_ANNUAL_REPORT
    assert "세부원칙" not in doc["html"] and "krx-cg" not in doc["html"]
    assert any(d["kind"] == "attached" for d in doc["docs"])       # 내용은 첨부 PDF 에 있다


async def test_unknown_acceptance_number_is_a_client_error_not_a_crash(kind_client):
    with pytest.raises(KindClientError):
        await kind_client.documents("20000101000001")


async def test_missing_body_path_is_a_client_error(kind_client):
    """정정 전 문서 등 — 경로 응답에 setPath 가 없으면 본문이 없다는 뜻이다."""
    with pytest.raises(KindClientError):
        await kind_client.document(SAMSUNG_2025, doc_no="99999999999999")


async def test_blocked_page_does_not_look_like_a_document():
    """Akamai 차단 페이지(200 + HTML)를 문서로 착각하지 않는다 — 클라우드에서 실제로 겪은 모양."""
    http = httpx.AsyncClient(transport=httpx.MockTransport(
        lambda r: httpx.Response(200, text="<html><body>Access Denied</body></html>")))
    client = KindClient(http, min_interval=0.0)
    with pytest.raises(KindClientError):
        await client.documents(SAMSUNG_2025)


def test_amended_document_is_marked_not_latest():
    """본문 옵션의 `|N` = 「이 문서 위에 정정본이 있다」."""
    html = ("<select id=\"mainDoc\" name=\"mainDoc\">"
            "<option value=''>본문선택</option>"
            "<option value='20240101000002|Y'>기업지배구조 보고서 공시 (2024.01.02)</option>"
            "<option value='20240101000001|N'>기업지배구조 보고서 공시 (2024.01.01)</option>"
            "</select>")
    docs = parse_documents(html)
    assert [d["latest"] for d in docs] == [True, False]


def test_body_url_and_form_number_come_from_setpath():
    body, toc = parse_body_url(
        "parent.setPath('https://kind.krx.co.kr/external/a/99667_toc.htm',"
        "'https://kind.krx.co.kr/external/a/99667.htm','/external/a/99667','01','30');")
    assert body.endswith("/99667.htm") and toc.endswith("_toc.htm")
    assert form_no(body) == codes.KIND_FORM_GOV_REPORT


def _offline_client() -> KindClient:
    return KindClient(httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(404))),
                      min_interval=0.0)


def test_small_notices_do_not_push_each_other_out():
    """지속가능경영보고서 서식(11KB)·첨부 목록(2KB)은 작다 — 10개사 × 2건을 동시에 열어도 캐시에 다 남는다.

    예전엔 개수 8건으로 막아서, 10개사를 동시에 열자 도구 호출마다 KIND 를 다시 불렀다(2026-09-24 부하 재현).
    """
    client = _offline_client()
    for i in range(20):
        client._store(f"notice{i}", {"html": "x" * 11_000})
    assert all(client._cached(f"notice{i}") is not None for i in range(20))


def test_big_bodies_are_still_capped_by_size(monkeypatch):
    """지배구조보고서 본문(5~12MB)은 여전히 막는다 — 상한을 개수가 아니라 글자 수로 옮긴 것뿐이다."""
    from open_esg_korea.krx import kind
    monkeypatch.setattr(kind, "_MAX_CACHE_CHARS", 30)
    client = _offline_client()
    for i in range(4):
        client._store(f"body{i}", {"html": "y" * 12})
    assert client._cached("body0") is None and client._cached("body3") is not None
    assert client._cache_chars() <= 30
