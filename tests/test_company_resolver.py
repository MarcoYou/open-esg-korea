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
    res = await resolve_company("바이오로직스", krx_client)
    assert res.status is AnalysisStatus.EXACT and res.selected["isu_cd"] == "207940"
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


# ── Phase 2: DART 명부로 코스닥 회사명 ───────────────────────────────────────────

async def test_kosdaq_name_resolves_through_dart_with_corp_code_and_warning(krx_client):
    res = await resolve_company("에코프로비엠", krx_client)
    assert res.status is AnalysisStatus.EXACT
    assert res.selected == {"isu_cd": "247540", "name": "에코프로비엠", "in_index": False, "match": "exact",
                            "corp_code": "01160363"}
    assert any("색인 밖" in w for w in res.warnings)


async def test_dart_exact_beats_portal_partial(krx_client):
    """「에코프로」— 포털 부분일치는 에코프로머티 하나지만 DART 에 정확히 「에코프로」(086520)가 있다."""
    res = await resolve_company("에코프로", krx_client)
    assert res.status is AnalysisStatus.EXACT and res.selected["isu_cd"] == "086520"
    assert res.selected["in_index"] is False


async def test_english_name_from_dart_works(krx_client):
    res = await resolve_company("Alteogen Inc.", krx_client)
    assert res.status is AnalysisStatus.EXACT and res.selected["isu_cd"] == "196170"


async def test_kospi_exact_hit_gets_corp_code_only_if_dart_is_already_loaded(krx_client, dart_index):
    res = await resolve_company("삼성전자", krx_client)
    assert res.selected["corp_code"] is None and dart_index.downloads == 0     # 포털에서 끝나면 DART 를 안 부른다
    await dart_index.listed()
    res = await resolve_company("삼성전자", krx_client)
    assert res.selected["corp_code"] == "00126380" and res.selected["in_index"] is True


async def test_partial_across_both_indexes_is_ambiguous_portal_first(krx_client):
    res = await resolve_company("에코프", krx_client)
    assert res.status is AnalysisStatus.AMBIGUOUS
    assert res.candidates[0] == {"isu_cd": "450080", "name": "에코프로머티", "in_index": True, "corp_code": "01311408"}
    assert {c["isu_cd"] for c in res.candidates} >= {"450080", "086520", "247540", "383310"}


async def test_kosdaq_partial_with_one_candidate_is_inferred(krx_client):
    res = await resolve_company("알테오", krx_client)
    assert res.status is AnalysisStatus.EXACT and res.selected["isu_cd"] == "196170"
    assert any("추정" in w for w in res.warnings) and any("색인 밖" in w for w in res.warnings)


async def test_duplicate_dart_names_stay_ambiguous(krx_client):
    res = await resolve_company("정다운", krx_client)
    assert res.status is AnalysisStatus.AMBIGUOUS and len(res.candidates) == 2


async def test_kosdaq_code_gets_corp_code_when_dart_is_loaded(krx_client, dart_index):
    await dart_index.listed()
    res = await resolve_company("247540", krx_client)
    assert res.selected["corp_code"] == "01160363" and res.selected["in_index"] is False


async def test_without_dart_key_the_bundled_snapshot_resolves_kosdaq_names(krx_client):
    from tests.conftest import make_dart_index
    idx = make_dart_index("", bundle=True)
    res = await resolve_company("에코프로비엠", krx_client, dart=idx)
    assert res.status is AnalysisStatus.EXACT and res.selected["isu_cd"] == "247540"
    assert res.selected["corp_code"] == "01160363" and idx.downloads == 0
    miss = await resolve_company("존재하지않는회사명", krx_client, dart=idx)
    assert miss.status is AnalysisStatus.ERROR and any("스냅샷" in w for w in miss.warnings)


async def test_stale_bundle_adds_a_warning(krx_client, monkeypatch):
    from tests.conftest import make_dart_index
    idx = make_dart_index("", bundle=True)
    monkeypatch.setattr(idx, "bundle_age_days", lambda: 400)
    res = await resolve_company("에코프로비엠", krx_client, dart=idx)
    assert res.status is AnalysisStatus.EXACT and any("400일" in w for w in res.warnings)


async def test_without_any_dart_index_behaviour_is_phase_1_plus_a_hint(krx_client):
    from tests.conftest import make_dart_index
    res = await resolve_company("에코프로비엠", krx_client, dart=make_dart_index(""))
    assert res.status is AnalysisStatus.ERROR
    assert any("OPENDART_API_KEY" in w for w in res.warnings)


async def test_dart_outage_falls_back_to_the_bundle(krx_client):
    from tests.conftest import make_dart_index
    down = make_dart_index("down", bundle=True)
    ok = await resolve_company("삼성전자", krx_client, dart=down)
    assert ok.status is AnalysisStatus.EXACT and ok.warnings == []
    res = await resolve_company("에코프로비엠", krx_client, dart=down)
    assert res.status is AnalysisStatus.EXACT and down.source == "bundle"


async def test_dart_outage_without_a_bundle_does_not_break_portal_resolution(krx_client):
    from tests.conftest import make_dart_index
    down = make_dart_index("down")
    ok = await resolve_company("삼성전자", krx_client, dart=down)
    assert ok.status is AnalysisStatus.EXACT and ok.warnings == []
    miss = await resolve_company("에코프로비엠", krx_client, dart=down)
    assert miss.status is AnalysisStatus.ERROR
    assert any("불러오지 못해" in w for w in miss.warnings)


# ── 별칭·음차·업종어 ───────────────────────────────────────────────────────────

async def test_colloquial_alias_resolves_exactly_and_says_so(krx_client):
    res = await resolve_company("현대차", krx_client)
    assert res.status is AnalysisStatus.EXACT and res.selected["isu_cd"] == "005380" and res.selected["match"] == "exact"
    assert any("통칭" in w for w in res.warnings) and not any("추정" in w for w in res.warnings)
    res = await resolve_company("하이닉스", krx_client)
    assert res.selected["isu_cd"] == "000660" and any("통칭" in w for w in res.warnings)


async def test_hangul_spelled_letters_match_latin_names(krx_client):
    res = await resolve_company("에스케이하이닉스", krx_client)
    assert res.status is AnalysisStatus.EXACT and res.selected["isu_cd"] == "000660" and res.warnings == []
    res = await resolve_company("삼성SDS", krx_client)
    assert res.status is AnalysisStatus.EXACT and res.selected["isu_cd"] == "018260"
    res = await resolve_company("엘지화학", krx_client)
    assert res.status is AnalysisStatus.EXACT and res.selected["isu_cd"] == "051910"


async def test_missing_industry_suffix_is_exact_not_inferred(krx_client):
    res = await resolve_company("삼성화재", krx_client)
    assert res.status is AnalysisStatus.EXACT and res.selected["isu_cd"] == "000810"
    assert not any("추정" in w for w in res.warnings)


def test_name_keys_transliterate_runs_anywhere():
    from open_esg_korea.services.company import name_keys
    assert "삼성sds" in name_keys("삼성에스디에스")
    assert "kt앤g" in name_keys("케이티앤지") and "kt앤g" in name_keys("KT&G")
    assert name_keys("이마트") == {"이마트"}                       # 1글자 run 은 건드리지 않는다
    assert "jyp엔터테인먼트" in name_keys("제이와이피엔터테인먼트")
