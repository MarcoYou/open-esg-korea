"""서비스 payload — 상태·경고·출처가 응답에 실리는지."""

from __future__ import annotations

from open_esg_korea.krx import codes
from open_esg_korea.services.esg_ratings import build_esg_ratings_payload
from open_esg_korea.services.governance import (build_governance_indicators_payload,
                                                build_governance_policies_payload, parse_policies)
from open_esg_korea.services.reports import build_esg_disclosures_payload, build_sustainability_reports_payload, parse_standards
from open_esg_korea.services.screener import build_screener_payload, grade_at_least, resolve_upjong


async def test_ratings_payload_carries_source_license_and_history(krx_client):
    p = await build_esg_ratings_payload("삼성전자", 2025, client=krx_client)
    assert p["status"] == "exact" and p["data"]["year"] == 2025
    assert p["source"]["provider"] == "KRX ESG 포털" and "esg.krx.co.kr" in p["source"]["page_url"]
    assert "저작물" in p["license"]
    assert [h["kcgs_esg"] for h in p["data"]["kcgs_history"]] == ["B", "B+", "B"]   # fixture 합성값


async def test_each_grade_carries_its_own_agencys_terms(krx_client):
    """기관마다 조건이 다르다 — 한 문장으로 뭉치면 어느 쪽으로든 틀린다."""
    p = await build_esg_ratings_payload("삼성전자", 2025, client=krx_client)
    terms = {r["agency_id"]: r["license"] for r in p["data"]["ratings"]}
    assert "대외 공개" in terms["kcgs"]                       # KCGS: 「비상업적 내부 용도·대외 공개 금지」
    assert "지수 산출" in terms["msci"]                       # MSCI: 용도 제한이 따로 붙는다
    assert "서면동의" in terms["sustinvest"] and "서면 허가" in terms["sp"]
    assert len(set(terms.values())) == 5                     # 한 기관 조항을 다섯 곳에 붙여쓰지 않는다
    assert all(terms.values())


async def test_every_agency_restricts_use_to_internal(krx_client):
    """다섯 곳 다 내부 용도다 — MSCI 도 예외가 아니다(영문 원문 「for internal use only」, 2026-09-08 확인).
    화면의 한글 요약만 보고 「MSCI 는 복제 제한이 없다」고 읽었던 것을 바로잡은 자리다."""
    p = await build_esg_ratings_payload("삼성전자", 2025, client=krx_client)
    terms = {r["agency_id"]: r["license"] for r in p["data"]["ratings"]}
    assert "내부 용도" in terms["kcgs"] and "내부 용도" in terms["msci"]
    for r in p["data"]["ratings"]:                            # 줄인 문장이라 원문 주소를 함께 준다
        assert r["license_url"].startswith("https://esg.krx.co.kr/templets/mobile/notice-box.jsp?type=")


async def test_blanket_notice_does_not_claim_one_agencys_clause_for_all(krx_client):
    """「비상업적 내부 용도」는 KCGS 조항이다 — 총괄 고지에 넣으면 MSCI 에 과하게 적용된다."""
    p = await build_esg_ratings_payload("삼성전자", 2025, client=krx_client)
    assert "저작물" in p["license"] and "사전승낙" in p["license"]
    assert "비상업적 내부 용도" not in p["license"]


async def test_source_points_at_this_companys_screen(krx_client):
    """값이 아니라 원본을 보고 싶을 때 바로 열려야 한다."""
    p = await build_esg_ratings_payload("삼성전자", 2025, client=krx_client)
    assert p["source"]["page_url"].endswith("?isu_cd=005930")


def test_rating_fixtures_do_not_carry_real_grades():
    """등급을 저장소에 두면 그 자체가 복제다 — fixture 는 스키마만 지킨다(규칙 6)."""
    import json, pathlib
    fix = pathlib.Path(__file__).parent / "fixtures"
    for name in ("ratings_005930_2025.json", "history_005930.json", "list_2025_head.json"):
        body = json.loads((fix / name).read_text(encoding="utf-8"))
        assert "합성값" in body.get("_note", ""), f"{name} 에 합성값 표시가 없다"


async def test_ratings_ambiguous_returns_candidates_not_grades(krx_client):
    p = await build_esg_ratings_payload("삼성", client=krx_client)
    assert p["status"] == "ambiguous" and p["data"]["candidates"] and "ratings" not in p["data"]


async def test_ratings_without_year_falls_back_and_says_so(krx_client, monkeypatch):
    # 「올해」를 2027 로 두면 fixture 는 빈 등급을 준다 → 전년(2026→fixture 2025 등급)으로 물러선다.
    monkeypatch.setattr("open_esg_korea.services.esg_ratings.current_year", lambda: 2027)
    p = await build_esg_ratings_payload("005930", client=krx_client)
    assert p["data"]["year"] == 2026 and any("아직 없어" in w for w in p["warnings"])


def test_standards_parsed_from_icon_html():
    html = '<span class="stan-icon gri"></span><span class="stan-icon tcfd"></span>'
    assert parse_standards(html) == ["GRI", "TCFD"] and parse_standards(None) == []


async def test_reports_payload_has_links_and_verifier(krx_client):
    p = await build_sustainability_reports_payload("삼성전자", client=krx_client)
    r = p["data"]["reports"][0]
    assert r["year"] == "2025" and r["third_party_verifier"] == "안진회계법인"
    assert set(r["standards"]) == {"GRI", "SASB", "TCFD", "UN SDGs"}
    # 접수번호는 KIND 번호다 — 같은 번호로 DART 를 열면 다른 회사 공시가 나온다(실측 2026-09-07). DART 링크는 싣지 않는다.
    assert set(r["links"]) == {"kind"} and r["links"]["kind"].endswith(r["acpt_no"])
    assert p["data"]["summary"]["report_count"] == "7"


async def test_disclosures_payload(krx_client):
    p = await build_esg_disclosures_payload("삼성전자", client=krx_client)
    assert p["status"] == "exact" and len(p["data"]["disclosures"]) == 3
    assert p["data"]["disclosures"][0]["title"] == "기업지배구조 보고서 공시"


async def test_governance_indicators_15_items_and_rate(krx_client):
    p = await build_governance_indicators_payload("삼성전자", 2025, client=krx_client)
    d = p["data"]
    assert d["compliance_rate"] == "86.7%" and len(d["indicators"]) == 15
    by_no = {i["no"]: i["complied"] for i in d["indicators"]}
    assert by_no[2] is True and by_no[9] is False          # 전자투표 O · 집중투표제 X
    assert d["complied_count"] == 13 and d["answered_count"] == 15


async def test_governance_indicators_missing_year_is_no_data_not_zero(krx_client):
    p = await build_governance_indicators_payload("삼성전자", 2020, client=krx_client)
    assert p["status"] == "no_data" and "indicators" not in p["data"]
    assert any("미준수" not in w or "아니라" in w for w in p["warnings"])


async def test_governance_compare_block(krx_client):
    p = await build_governance_indicators_payload("삼성전자", 2025, compare="SK하이닉스", client=krx_client)
    assert p["data"]["compare"]["company"]["isu_cd"] == "000660"
    assert any("비교회사" in w for w in p["warnings"])     # fixture 엔 하이닉스 지표가 없다 → 경고


def test_every_policy_key_has_label_and_fact_items_flagged():
    row = {k: "O" for k in codes.GOV_POLICIES}
    items = parse_policies(row)
    assert len(items) == 74 and all(i["label"] for i in items)
    assert {i["no"] for i in items if i["fact_item"]} == codes.GOV_POLICY_FACT_ITEMS


async def test_policies_payload_counts_exclude_fact_items(krx_client):
    p = await build_governance_policies_payload("삼성전자", 2025, client=krx_client)
    items = p["data"]["policies"]
    assert p["data"]["adopted_count"] == sum(1 for i in items if i["adopted"] and not i["fact_item"])
    assert all(i["adopted"] is not None for i in items)     # fixture 는 74 키 전부 채워져 있다


def test_grade_order_is_per_agency_only():
    assert grade_at_least("kcgs", "A", "B+") and not grade_at_least("kcgs", "B", "B+")
    assert grade_at_least("msci", "AA", "AA") and not grade_at_least("msci", "BBB", "A")
    assert not grade_at_least("kcgs", None, "A") and not grade_at_least("sp", "43", "A")


def test_upjong_by_name_or_code():
    assert resolve_upjong("전기·전자") == "3015" == resolve_upjong("3015") == resolve_upjong("전기전자")
    assert resolve_upjong("") == "" and resolve_upjong("없는업종") == ""


async def test_screener_filters_locally(krx_client):
    p = await build_screener_payload(year=2025, min_kcgs="A", client=krx_client)
    assert p["data"]["universe_count"] == 5
    assert all(c["ratings"]["kcgs"]["esg"] in ("A", "A+", "S") for c in p["data"]["companies"])
    assert p["data"]["matched_count"] == len(p["data"]["companies"])
    p2 = await build_screener_payload(year=2025, min_kcgs="A", industry="우주산업", client=krx_client)
    assert any("업종" in w for w in p2["warnings"])
