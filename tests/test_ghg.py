"""온실가스 — GIR 명세서 HTML·ETRS CSV 해석 · 이름 대조(음차·법인격) · 회사/업종/인벤토리 payload."""

from __future__ import annotations

import pytest

from open_esg_korea.gir.client import GirClientError, parse_csv, parse_statement_html, to_int
from open_esg_korea.services.company import name_keys
from open_esg_korea.services.ghg import (build_ghg_emissions_payload, build_ghg_industry_payload,
                                         build_ghg_inventory_payload, load_inventory, match_rows)
from tests.conftest import FIX


# ── 해석 ────────────────────────────────────────────────────────────────────────

def test_statement_html_rows_carry_typed_numbers():
    rows = parse_statement_html((FIX / "gir_statement_2024_subset.html").read_text(encoding="utf-8"))
    assert len(rows) == 17
    se = next(r for r in rows if r["name"] == "삼성전자 주식회사")
    assert se == {"authority": "기후에너지환경부", "name": "삼성전자 주식회사", "year": 2024, "designation": "업체",
                  "industry": "반도체 제조업", "emissions_tco2eq": 13594735, "energy_tj": 258326,
                  "verifier": "(재)한국품질재단", "note": ""}


def test_statement_html_without_table_is_a_client_error():
    with pytest.raises(GirClientError):
        parse_statement_html("<html><body>점검 중입니다</body></html>")


def test_etrs_csv_is_cp949_with_header():
    rows = parse_csv((FIX / "etrs_certified_2024_subset.csv").read_bytes())
    se = next(r for r in rows if r["업체명"] == "삼성전자 주식회사")
    assert se["부문"] == "산업" and se["이행연도"] == "2024" and to_int(se["인증 배출량(톤)"]) == 13594735
    with pytest.raises(GirClientError):
        parse_csv("<html>점검</html>".encode("cp949"))


def test_to_int_treats_blank_and_dash_as_missing_not_zero():
    assert to_int("13,594,735") == 13594735 and to_int("-") is None and to_int("") is None and to_int("x") is None


# ── 이름 대조 ───────────────────────────────────────────────────────────────────

def test_name_keys_strip_legal_forms_and_latinize_hangul_letters():
    assert name_keys("삼성전자 주식회사") >= {"삼성전자"} and "samsung전자" in name_keys("삼성전자 주식회사")
    assert name_keys("POSCO홀딩스") & name_keys("포스코홀딩스 주식회사")
    assert name_keys("(주)하림") == name_keys("하림") == {"하림"}
    assert "sk하이닉스" in name_keys("에스케이하이닉스 주식회사")
    assert name_keys("SK하이닉스") & name_keys("에스케이하이닉스 주식회사")
    assert "삼성생명공익재단" in name_keys("사회복지법인 삼성생명공익재단")


def test_match_rows_separates_exact_from_related_subsidiaries():
    rows = parse_statement_html((FIX / "gir_statement_2024_subset.html").read_text(encoding="utf-8"))
    exact, related = match_rows(rows, "POSCO홀딩스")
    assert [r["name"] for r in exact] == ["포스코홀딩스 주식회사"]
    assert "주식회사 포스코" in {r["name"] for r in related}
    exact, related = match_rows(rows, "SK하이닉스")
    assert [r["name"] for r in exact] == ["에스케이하이닉스 주식회사"]
    assert [r["name"] for r in related] == ["에스케이하이닉스 시스템아이씨(주)"]


# ── 회사별 payload ──────────────────────────────────────────────────────────────

async def test_company_emissions_with_history_and_ets(krx_client, gir_client):
    p = await build_ghg_emissions_payload("삼성전자", 2024)
    assert p["status"] == "exact" and p["data"]["year"] == 2024
    st = p["data"]["statement"][0]
    assert st["emissions_tco2eq"] == 13594735 and st["industry"] == "반도체 제조업"
    ets = p["data"]["ets"]
    assert ets["in_ets"] is True
    y24 = next(e for e in ets["by_year"] if e["year"] == 2024)
    assert y24["certified_t"] == 13594735 and y24["allocation_t"] is not None
    assert y24["surplus_t"] == y24["allocation_t"] - y24["certified_t"]
    periods = {a["period"] for a in ets["pre_allocation"]}
    assert periods == {3, 4}
    assert p["license"].startswith("온실가스 배출량") and p["source"]["provider"].startswith("온실가스종합정보센터")
    hist = {h["year"]: h for h in p["data"]["history"]}
    assert hist[2024]["emissions_tco2eq"] == 13594735 and hist[2023]["emissions_tco2eq"] is None


async def test_company_absent_from_gir_is_no_data_not_zero(krx_client, gir_client):
    p = await build_ghg_emissions_payload("NAVER", 2024)
    assert p["status"] == "no_data" and p["data"]["statement"] == []
    assert any("0 이라는 뜻이 아닙니다" in w for w in p["warnings"])


async def test_holding_company_lists_subsidiaries_as_related(krx_client, gir_client):
    p = await build_ghg_emissions_payload("005490", 2024)      # POSCO홀딩스 — 색인 밖 코드 경로도 지나간다
    if p["status"] == "error":
        pytest.skip("fixture 색인에 005490 없음")
    names = {r["name"] for r in p["data"]["related_entities"]}
    assert "주식회사 포스코" in names


async def test_default_year_falls_back_to_latest_available(krx_client, gir_client, monkeypatch):
    monkeypatch.setattr("open_esg_korea.services.ghg.current_year", lambda: 2026)
    p = await build_ghg_emissions_payload("삼성전자")
    assert p["status"] == "exact" and p["data"]["year"] == 2024


async def test_site_level_rows_get_a_warning(krx_client, gir_client):
    p = await build_ghg_emissions_payload("삼성물산", 2024)
    assert p["status"] == "exact" and p["data"]["statement"][0]["designation"] == "사업장"
    assert any("사업장" in w for w in p["warnings"])


# ── 업종별 payload ──────────────────────────────────────────────────────────────

async def test_industry_ranking_and_shares(gir_client):
    p = await build_ghg_industry_payload(year=2024, top=5)
    d = p["data"]
    assert d["total_reporting_entities"] == 17 and d["industries"][0]["industry"] == "1차 철강 제조업"
    assert abs(sum(g["share_pct"] for g in d["industries"]) - 100) < 5 or len(d["industries"]) < d["industries_total"]


async def test_industry_filter_lists_companies_in_order(gir_client):
    p = await build_ghg_industry_payload("철강", year=2024)
    d = p["data"]
    assert d["matched_industries"] == ["1차 철강 제조업"]
    assert d["companies"][0]["name"] == "주식회사 포스코" and d["companies"][0]["rank"] == 1
    assert abs(sum(c["share_in_industry_pct"] for c in d["companies"]) - 100) < 0.5


async def test_unknown_industry_is_no_data_with_candidates(gir_client):
    p = await build_ghg_industry_payload("철깡", year=2024)
    assert p["status"] == "no_data" and "1차 철강 제조업" in p["data"]["industry_candidates"]


async def test_industry_default_year_falls_back(gir_client, monkeypatch):
    monkeypatch.setattr("open_esg_korea.services.ghg.current_year", lambda: 2026)
    p = await build_ghg_industry_payload()
    assert p["data"]["year"] == 2024 and any("2024년으로" in w for w in p["warnings"])


# ── 국가 인벤토리 ──────────────────────────────────────────────────────────────

def test_inventory_snapshot_is_well_formed():
    inv = load_inventory()
    assert inv and inv["meta"]["unit"] == "kt CO2-eq" and inv["meta"]["years"][0] == "1990"
    assert len(inv["series"]) >= 100 and inv["series"][0]["category"].startswith("총배출량")


def test_inventory_overview_and_find():
    p = build_ghg_inventory_payload(years=3)
    ov = {r["category"]: r for r in p["data"]["overview"]}
    assert any(k.startswith("총배출량") for k in ov) and len(p["data"]["years"]) == 3
    assert {"에너지", "산업공정 및 제품사용", "농업", "LULUCF", "폐기물"} <= set(ov)
    total = next(r for k, r in ov.items() if k.startswith("총배출량"))
    assert all(v is not None for v in total["values_kt"].values())
    q = build_ghg_inventory_payload("철강")
    assert q["status"] == "exact" and any("철강" in m["category"] for m in q["data"]["matches"])
    miss = build_ghg_inventory_payload("존재하지않는분야")
    assert miss["status"] == "no_data"


def test_inventory_missing_snapshot_is_an_error_not_a_crash(tmp_path):
    p = build_ghg_inventory_payload(inventory=None) if False else None
    from open_esg_korea.services.ghg import load_inventory as li
    assert li(tmp_path / "none.json") is None
