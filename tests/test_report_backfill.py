"""포털 목록이 못 따라온 최신 연도를 KIND 공시로 메운다 (network 0).

왜 필요했나 — 2026-09-08 실측:
  · 포털 지속가능경영보고서 목록: 2019~2025 (발행년도 선택지에 2026 이 아예 없다)
  · 같은 날 KIND: 2026년 자율공시 259건, 삼성전자는 2026-06-26 (`20260626000871`)
「최신 보고서가 통째로 안 보이는」 것이 이 도구에서 가장 아픈 구멍이라 메운다.

이 파일이 지키는 것: 메운 행을 **포털 행인 척하지 않는 것**. 포털 집계 열(업종·작성기준·검증기관)이
비어 있는 이유를 응답과 표에서 밝혀야 한다 — 빈 칸은 「없다」가 아니라 「아직 집계 전」이다.
"""

from __future__ import annotations

import httpx
import pytest

from open_esg_korea.krx import codes
from open_esg_korea.krx.kind import parse_search_rows
from open_esg_korea.services.reports import build_sustainability_reports_payload
from open_esg_korea.tools.sustainability_reports import _render


def test_parses_acptno_from_the_onclick_not_the_href():
    """접수번호는 링크 주소가 아니라 `openDisclsViewer('…')` 인자에 있다 — 여기서 한 번 틀렸었다."""
    html = ("<tr><td>1</td><td>2026-06-26 16:05</td><td>삼성전자</td>"
            "<td><a href=\"#viewer\" onclick=\"openDisclsViewer('20260626000871','')\">"
            "지속가능경영보고서 등 관련사항(자율공시)</a></td></tr>")
    assert parse_search_rows(html) == [{"acpt_no": "20260626000871", "disclosed_at": "2026-06-26",
                                        "title": "지속가능경영보고서 등 관련사항(자율공시)"}]


def test_rows_without_an_acceptance_number_are_dropped():
    """머리글·안내 문구 행이 섞여 들어오면 안 된다."""
    assert parse_search_rows("<tr><th>날짜</th><th>공시제목</th></tr>") == []
    assert parse_search_rows("<tr><td>조회된 내용이 없습니다.</td></tr>") == []


async def test_search_needs_the_A_prefix_and_a_post_body(kind_client):
    """KIND 는 형식이 어긋나면 오류가 아니라 **안내 페이지**를 준다 — 0건과 구분되게 호출 모양을 못 박는다."""
    rows = await kind_client.search(isu_cd="005930", name="삼성전자",
                                    from_date="2026-01-01", to_date="2026-12-31",
                                    report_nm=codes.KIND_SEARCH_SUSTAINABILITY)
    assert [r["acpt_no"] for r in rows] == ["20260626000871"]


async def test_missing_year_is_filled_from_kind(krx_client):
    payload = await build_sustainability_reports_payload("삼성전자", client=krx_client)
    reports = payload["data"]["reports"]
    years = [r["year"] for r in reports]
    assert years == sorted(years, reverse=True) and years[0] == "2026"

    newest = reports[0]
    assert newest["source"] == "kind" and newest["acpt_no"] == "20260626000871"
    assert all(r["source"] == "portal" for r in reports[1:])


async def test_the_filled_row_does_not_pretend_to_have_portal_columns(krx_client):
    """업종·작성기준·검증기관은 포털 집계 값이다 — 지어내지 않고 비운 뒤 이유를 밝힌다."""
    payload = await build_sustainability_reports_payload("삼성전자", client=krx_client)
    newest = payload["data"]["reports"][0]
    assert newest["industry"] is None and newest["standards"] == []
    assert newest["third_party_verifier"] is None
    assert any("포털 목록에 아직 없어" in w for w in payload["warnings"])

    text = _render(payload)
    assert "⁽ᴷᴵᴺᴰ⁾" in text and "「없다」가 아니라" in text


async def test_no_extra_call_when_the_portal_is_current(krx_client, monkeypatch):
    """빠진 해가 없으면 KIND 를 부르지 않는다 — 규칙 1(간격 0.5초)은 안 부르는 것이 제일 낫다."""
    called = []

    async def boom(*args, **kwargs):
        called.append(1)
        return []

    monkeypatch.setattr("open_esg_korea.services.reports.current_year", lambda: 2025)
    await build_sustainability_reports_payload("삼성전자", client=krx_client, kind=None)
    # 2025 가 최신이면 메울 해가 없다 — 위 monkeypatch 로 to_year 상한이 2025 가 된다
    payload = await build_sustainability_reports_payload("삼성전자", client=krx_client)
    assert payload["data"]["reports"][0]["year"] == "2025"
    assert not any("포털 목록에 아직 없어" in w for w in payload["warnings"])


async def test_kind_failure_keeps_the_portal_list(krx_client, kind_client, monkeypatch):
    """보조 조회가 죽어도 목록은 살아야 한다(규칙 5 — 외부 실패는 degrade)."""
    async def boom(*args, **kwargs):
        raise httpx.ConnectError("KIND 지연")

    monkeypatch.setattr(kind_client, "search", boom)
    payload = await build_sustainability_reports_payload("삼성전자", client=krx_client, kind=kind_client)
    assert payload["status"] == "exact" and payload["data"]["reports"]
    assert payload["data"]["reports"][0]["year"] == "2025"
    assert any("KIND 에서 확인하지 못했습니다" in w for w in payload["warnings"])


async def test_amended_filing_replaces_the_original_for_that_year(krx_client, kind_client, monkeypatch):
    """한 해에 원본과 정정이 함께 나올 수 있다 — 마지막 것 하나만 싣고 정정임을 밝힌다.

    드물지만 실재한다(2026-09-08 실측: 2026년 436건 중 4 · 2025년 408건 중 1 · 2024년 296건 중 1).
    포털도 기본값은 「정정 전 공시 제외」다.
    """
    async def two_rows(*args, **kwargs):
        return [{"acpt_no": "20260626000871", "disclosed_at": "2026-06-26",
                 "title": "지속가능경영보고서 등 관련사항(자율공시)"},
                {"acpt_no": "20260701000123", "disclosed_at": "2026-07-01",
                 "title": "[정정]지속가능경영보고서 등 관련사항(자율공시)"}]

    monkeypatch.setattr(kind_client, "search", two_rows)
    payload = await build_sustainability_reports_payload("삼성전자", client=krx_client, kind=kind_client)
    rows_2026 = [r for r in payload["data"]["reports"] if r["year"] == "2026"]
    assert len(rows_2026) == 1
    assert rows_2026[0]["acpt_no"] == "20260701000123" and rows_2026[0]["amended"] is True


async def test_the_window_covers_the_whole_year_not_just_june(kind_client, krx_client, monkeypatch):
    """공시가 6월에 몰리지만 꼬리가 12월까지 간다 — 창을 좁히면 늦게 낸 회사를 놓친다.

    실측(2026-09-08): 2025년 408건 중 6월 299 · 7월 55 · 8월 32 · 9~12월 14.
    """
    seen = {}

    async def capture(*, isu_cd, name, from_date, to_date, report_nm=""):
        seen.update(from_date=from_date, to_date=to_date)
        return []

    monkeypatch.setattr(kind_client, "search", capture)
    await build_sustainability_reports_payload("삼성전자", client=krx_client, kind=kind_client)
    assert seen["from_date"].endswith("-01-01") and seen["to_date"].endswith("-12-31")
