"""회사 식별 — 코드 직행 · 정확 · 부분 추정 · 모호 · 실패."""

from __future__ import annotations

from open_esg_korea.services.company import normalize, resolve_company
from open_esg_korea.services.contracts import AnalysisStatus


def test_normalize_strips_legal_form_and_spaces():
    assert normalize("삼성전자(주)") == normalize(" 삼성 전자 ") == "삼성전자"
    assert normalize("주식회사 삼성전자") == "삼성전자"


async def test_exact_name(krx_client):
    res = await resolve_company("삼성전자", krx_client)
    assert res.status is AnalysisStatus.EXACT and res.selected["isu_cd"] == "005930"
    assert res.warnings == []


async def test_six_digit_code_bypasses_index_and_is_labelled(krx_client):
    res = await resolve_company("005930", krx_client)
    assert res.status is AnalysisStatus.EXACT and res.selected["name"] == "삼성전자" and res.selected["in_index"]


async def test_kosdaq_code_outside_index_is_accepted_with_a_warning(krx_client):
    res = await resolve_company("247540", krx_client)
    assert res.status is AnalysisStatus.EXACT and res.selected["name"] == "에코프로비엠"
    assert res.selected["in_index"] is False and any("색인 밖" in w for w in res.warnings)


async def test_unknown_code_is_an_error(krx_client):
    res = await resolve_company("000001", krx_client)
    assert res.status is AnalysisStatus.ERROR


async def test_partial_match_with_one_candidate_is_inferred_and_declared(krx_client):
    res = await resolve_company("하이닉스", krx_client)
    assert res.status is AnalysisStatus.EXACT and res.selected["isu_cd"] == "000660"
    assert any("추정" in w for w in res.warnings)


async def test_partial_match_with_many_candidates_is_ambiguous(krx_client):
    res = await resolve_company("삼성", krx_client)
    assert res.status is AnalysisStatus.AMBIGUOUS
    names = [c["name"] for c in res.candidates]
    assert "삼성전자" in names and len(names) > 1 and res.selected is None


async def test_no_match_is_error_with_close_suggestions(krx_client):
    res = await resolve_company("삼성전지", krx_client)
    assert res.status is AnalysisStatus.ERROR
    assert any(c["isu_cd"] == "005930" for c in res.candidates)
