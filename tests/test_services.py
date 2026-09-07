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
    assert [h["kcgs_esg"] for h in p["data"]["kcgs_history"]] == ["A", "B+", "A"]


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
    assert r["links"]["dart"].endswith(r["acpt_no"]) and "kind.krx.co.kr" in r["links"]["kind"]
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
