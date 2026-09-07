"""governance_report 도구 — 접수번호 고르기·scope·find·금융회사 분기·렌더링.

fixture 는 삼성전자 2025(원칙 1-1·4-4·7-2)·2026(1-4·8-1)과 KB금융 2025(연차보고서) 스냅샷이다.
"""

from __future__ import annotations

import json

import pytest

from open_esg_korea.services.governance_report_payload import build_governance_report_payload
from open_esg_korea.tools.governance_report import _render


@pytest.fixture
def wired(krx_client, kind_client):
    """포털·KIND 둘 다 fixture 로 갈아 끼운 상태."""
    return krx_client, kind_client


async def test_default_reads_the_latest_filing(wired):
    payload = await build_governance_report_payload("삼성전자")
    assert payload["status"] == "exact"
    filing = payload["data"]["filing"]
    assert filing["acpt_no"] == "20260601000268" and filing["filed_year"] == 2026


async def test_filing_year_and_disclosure_period_are_different_things(wired):
    """2025 년에 낸 보고서가 다루는 기간은 2024 년이다 — 헷갈리면 한 해 어긋난 답을 준다."""
    payload = await build_governance_report_payload("삼성전자", year=2025)
    data = payload["data"]
    assert data["filing"]["filed_year"] == 2025
    assert data["period"] == {"start": "2024-01-01", "end": "2024-12-31"}


async def test_missing_year_falls_back_to_latest_with_a_warning(wired):
    payload = await build_governance_report_payload("삼성전자", year=2019)
    assert payload["data"]["filing"]["filed_year"] == 2026
    assert any("2019년 제출본이 없어" in w for w in payload["warnings"])


async def test_find_selects_one_principle(wired):
    payload = await build_governance_report_payload("삼성전자", year=2025, find="4-4")
    principles = payload["data"]["principles"]
    assert [p["no"] for p in principles] == ["4-4"]
    assert principles[0]["answer"].startswith("당사는 임원의 선임시")
    assert payload["data"]["counts"]["principles"] == 3      # 읽은 것은 3개, 고른 것은 1개


async def test_find_by_keyword_searches_answer_and_reason(wired):
    payload = await build_governance_report_payload("삼성전자", year=2025, find="영업 상의 비밀")
    assert [p["no"] for p in payload["data"]["principles"]] == ["7-2"]


async def test_find_with_no_hit_says_so_instead_of_looking_empty(wired):
    payload = await build_governance_report_payload("삼성전자", year=2025, find="존재하지않는키워드")
    assert payload["data"]["principles"] == []
    assert any("걸리는 항목이 없습니다" in w for w in payload["warnings"])


async def test_notes_scope_pairs_reasons_with_the_failing_indicators(wired):
    payload = await build_governance_report_payload("삼성전자", scope="notes")
    data = payload["data"]
    assert data["indicators_not_complied"] == ["현금 배당관련 예측가능성 제공", "집중투표제 채택"]
    assert {n["no"] for n in data["notes"]} == {"1-4", "8-1"}
    assert "예측가능성" in data["notes"][0]["deficiency"]


async def test_tables_scope_returns_the_form_table_with_aligned_columns(wired):
    payload = await build_governance_report_payload("삼성전자", year=2025, scope="tables", find="7-2-1")
    table = payload["data"]["tables"][0]
    assert table["title"] == "최근 3년간 이사 출석률 및 안건 찬성률"
    assert {len(r) for r in table["header"] + table["rows"]} == {11}


async def test_financial_company_is_no_data_with_the_annual_report_warning(wired):
    """KB금융은 「연차보고서」로 갈음한다 — 원문(5~12MB)을 받기 전에 목록 제목만 보고 끊는다."""
    payload = await build_governance_report_payload("KB금융")
    assert payload["status"] == "no_data" and payload["data"]["form"] == "annual_report"
    assert any("연차보고서" in w for w in payload["warnings"])
    assert wired[1].calls == 0                              # KIND 를 부르지 않았다


async def test_license_is_the_disclosure_notice_not_the_rating_agencies(wired):
    """원문은 회사가 제출한 공시다 — 평가기관 등급 고지를 붙이면 권리자가 틀린다."""
    payload = await build_governance_report_payload("삼성전자", year=2025)
    assert "상장법인이 작성·제출" in payload["license"]
    assert "MSCI" not in payload["license"]


async def test_markdown_shows_answer_reason_and_source(wired):
    text = _render(await build_governance_report_payload("삼성전자", year=2025, find="7-2"))
    assert "## 세부원칙 7-2" in text
    assert "미진한 부분 및 그 사유: 개별이사별 활동내역" in text
    assert "kind.krx.co.kr/common/disclsviewer.do?method=search&acptno=20250530001005" in text


async def test_markdown_table_flattens_the_stacked_header(wired):
    text = _render(await build_governance_report_payload("삼성전자", year=2025, scope="tables", find="7-2-1"))
    assert "| 출석률 (%) 최근 3개년 평균 |" in text
    assert "| 김기남 | 사내이사(Inside) |" in text


async def test_json_format_carries_every_row(wired):
    from open_esg_korea.services.contracts import as_pretty_json
    payload = await build_governance_report_payload("삼성전자", year=2025, scope="tables", find="7-2-1")
    parsed = json.loads(as_pretty_json(payload))
    assert len(parsed["data"]["tables"][0]["rows"]) == 20


async def test_keyword_search_also_looks_inside_the_form_tables(wired):
    """회사가 답변에 안 쓰고 표에만 적는 말이 있다 — 표를 안 보면 「없음」이 되어 오해를 부른다."""
    payload = await build_governance_report_payload("삼성전자", year=2025, find="김기남")
    assert [p["no"] for p in payload["data"]["principles"]] == ["7-2"]   # 출석률 표 7-2-1 에만 있는 이름
    assert "김기남" not in payload["data"]["principles"][0]["answer"]


async def test_no_filing_at_all_does_not_print_an_empty_report_line(wired):
    payload = await build_governance_report_payload("에코프로비엠")
    assert payload["status"] == "no_data" and "filing" not in payload["data"]
    assert "보고서: -" not in _render(payload)
