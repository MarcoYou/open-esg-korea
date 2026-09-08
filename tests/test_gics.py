"""GICS 산업분류 — 동봉 스냅샷 조회·산업군 필터·산업군 안 등급 분포.

스냅샷은 2026-08-04 기준 KOSPI·KOSDAQ 2,534종목이다(`scripts/refresh_krx_gics.py` 로만 갱신).
분류가 개편되면 이 테스트가 먼저 깨진다 — 그게 의도다.
"""

from __future__ import annotations

import pytest

from open_esg_korea.services import gics
from open_esg_korea.services.rating_context import MIN_PEERS, build_context
from open_esg_korea.services.screener import build_screener_payload


def test_snapshot_covers_both_markets():
    meta = gics.meta()
    assert meta["rows"] > 2000 and set(meta["markets"]) == {"KOSPI", "KOSDAQ"}


def test_classify_returns_sector_and_group():
    hit = gics.classify("005930")
    assert hit["group_code"] == "4520" and hit["group"] == "하드웨어및IT장비"
    assert hit["sector_code"] == "45" and hit["sector"] == "정보기술"


def test_kosdaq_is_classified_too():
    """포털 업종은 유가증권만 다루지만 GICS 스냅샷은 코스닥도 담는다."""
    hit = gics.classify("247540")               # 에코프로비엠
    assert hit and hit["market"] == "KOSDAQ"


def test_missing_code_says_so_instead_of_guessing():
    assert gics.classify("999999") is None
    note = gics.annotate("999999")
    assert note["gics"] is None and "스냅샷에 이 종목이 없습니다" in note["note"]


def test_resolve_group_accepts_code_name_or_sector():
    assert [g["group_code"] for g in gics.resolve_group("4520")] == ["4520"]
    assert [g["group_code"] for g in gics.resolve_group("하드웨어")] == ["4520"]
    assert {g["sector"] for g in gics.resolve_group("정보기술")} == {"정보기술"}
    assert gics.resolve_group("없는산업군") == []


def test_members_can_be_narrowed_by_market():
    everyone = gics.members(group_code="4520")
    kospi = gics.members(group_code="4520", market="KOSPI")
    assert 0 < len(kospi) < len(everyone)


def test_groups_lists_what_you_can_slice_by():
    groups = gics.groups()
    assert len(groups) >= 20
    assert all(len(g["group_code"]) == 4 and g["count"] > 0 for g in groups)


# ── 등급 분포에 산업군 비교군을 얹는 부분 ────────────────────────────────────
def _rows(*pairs: tuple[str, str]) -> list[dict]:
    return [{"isu_cd": code, "kcgs_esg": grade} for code, grade in pairs]


def rating(esg: str) -> dict:
    return {"agency_id": "kcgs", "agency": "KCGS", "esg": esg, "coverage": True}


def test_peer_group_counts_within_the_same_industry():
    """전체 795사보다 같은 산업군이 「좋은 편인가」에 맞는 비교군이다."""
    peers = [r["isu_cd"] for r in gics.members(group_code="4520")][:6]
    rows = _rows(*[(c, "A") for c in peers[:5]], (peers[5], "D"))
    rows.append({"isu_cd": "999999", "kcgs_esg": "D"})          # 다른 산업군 — 비교군에서 빠져야 한다
    ctx = build_context(rows, [rating("A")], isu_cd=peers[0])
    peer = ctx["by_agency"]["kcgs"]["peer_group"]
    assert peer["rated"] == 6 and peer["at_or_above"] == 5      # 7행 중 산업군 6사만 셌다
    assert ctx["gics_group"]["group_code"] == "4520"


def test_tiny_industry_samples_are_dropped_rather_than_shown():
    """3~4사에서 「이 등급 이상 2사」는 오해만 부른다 — 표본이 작으면 아예 안 싣는다."""
    peers = [r["isu_cd"] for r in gics.members(group_code="4520")][:MIN_PEERS - 1]
    ctx = build_context(_rows(*[(c, "A") for c in peers]), [rating("A")], isu_cd=peers[0])
    assert "peer_group" not in ctx["by_agency"]["kcgs"]


def test_company_without_classification_gets_no_peer_group():
    ctx = build_context(_rows(("999999", "A")), [rating("A")], isu_cd="999999")
    assert "peer_group" not in ctx["by_agency"]["kcgs"] and "gics_group" not in ctx


# ── 스크리너 ────────────────────────────────────────────────────────────────
async def test_screener_filters_by_industry_group(krx_client):
    payload = await build_screener_payload(year=2025, gics_group="하드웨어", client=krx_client)
    groups = {(c.get("gics") or {}).get("group_code") for c in payload["data"]["companies"]}
    assert groups <= {"4520"}
    assert payload["data"]["filters"]["gics_group"] == ["하드웨어및IT장비"]


async def test_unknown_industry_group_warns_and_does_not_filter(krx_client):
    payload = await build_screener_payload(year=2025, gics_group="없는산업군", client=krx_client)
    assert payload["data"]["filters"]["gics_group"] is None
    assert any("찾지 못해 산업군 필터 없이" in w for w in payload["warnings"])


async def test_screener_reports_where_the_matches_cluster(krx_client):
    payload = await build_screener_payload(year=2025, client=krx_client)
    breakdown = payload["data"]["gics_breakdown"]
    assert breakdown and sum(r["count"] for r in breakdown) == len(payload["data"]["companies"])


async def test_company_block_carries_the_industry(krx_client):
    from open_esg_korea.services.esg_ratings import build_esg_ratings_payload
    payload = await build_esg_ratings_payload("삼성전자", 2025, client=krx_client)
    assert payload["data"]["company"]["gics"]["group"] == "하드웨어및IT장비"


def test_gics_is_kept_separate_from_the_other_industry_schemes():
    """같은 회사가 체계마다 다른 이름을 받는다 — 한 표에 섞으면 안 된다."""
    from open_esg_korea.krx import codes
    assert "하드웨어및IT장비" not in codes.UPJONG_CODES.values()   # 포털 업종엔 없는 이름
    assert "GICS" in codes.GICS_NOTICE and "섞지 마세요" in codes.GICS_NOTICE
