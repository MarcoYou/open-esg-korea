"""같은 기관 안의 등급 분포 (4b) — 「상위 N%」를 만들지 않는 이유를 코드로 못 박는다.

수치는 2026-09-08 실호출(2025년 유가증권 795사)에서 확인한 분포를 축소한 것이다.
"""

from __future__ import annotations

from open_esg_korea.services.esg_ratings import build_esg_ratings_payload
from open_esg_korea.services.rating_context import READING_NOTES, build_context
from open_esg_korea.tools.esg_ratings import _distribution_lines


def rows(**by_agency: list[str]) -> list[dict]:
    """전체 목록 흉내 — 기관별 열(`kcgs_esg`·`msci_esg`·`sv_esg`…)에 등급을 늘어놓는다."""
    length = max(len(v) for v in by_agency.values())
    out = []
    for i in range(length):
        row = {}
        for prefix, values in by_agency.items():
            row[f"{prefix}_esg"] = values[i] if i < len(values) else "-"
        out.append(row)
    return out


def rating(agency_id: str, agency: str, esg):
    return {"agency_id": agency_id, "agency": agency, "esg": esg, "coverage": True}


def test_counts_are_reported_instead_of_a_percentile():
    """한국ESG연구소는 A 에 61%가 동점이다 — 「상위 12%」 같은 값은 지어낸 정밀도다."""
    universe = rows(kesg=["A+"] * 2 + ["A"] * 12 + ["B+"] * 6)
    ctx = build_context(universe, [rating("kesg", "한국ESG연구소", "A")])["by_agency"]["kesg"]
    assert ctx["rated"] == 20
    assert ctx["at_or_above"] == 14 and ctx["same_grade"] == 12      # A 이상 14사, 그 중 12사가 동점
    assert "percentile" not in ctx and "rank" not in ctx


def test_unrated_companies_are_not_counted_as_bad():
    """`-` 는 미평가다 — 분모에 넣으면 등급이 실제보다 좋아 보인다."""
    universe = rows(msci=["AAA", "AA", "-", "-", "-", "-"])
    ctx = build_context(universe, [rating("msci", "MSCI", "AA")])["by_agency"]["msci"]
    assert ctx["rated"] == 2 and ctx["at_or_above"] == 2


def test_coverage_is_reported_because_agencies_cover_different_universes():
    """MSCI 는 795사 중 74사만 평가한다 — 분모를 감추면 「전체 중 상위권」으로 오해된다."""
    universe = rows(msci=["AAA", "AA"] + ["-"] * 8)
    ctx = build_context(universe, [rating("msci", "MSCI", "AA")], universe=10)["by_agency"]["msci"]
    assert ctx["coverage_pct"] == 20.0                              # 10사 중 2사만 평가


def test_a_low_grade_shows_up_as_most_companies_being_above():
    """삼성전자 서스틴베스트 B 는 「이 등급 이상 88%」다 — 등급만 봐서는 모른다."""
    universe = rows(sv=["AA"] * 1 + ["A"] * 3 + ["BB"] * 4 + ["B"] * 2)
    ctx = build_context(universe, [rating("sustinvest", "서스틴베스트", "B")])["by_agency"]["sustinvest"]
    assert ctx["at_or_above"] == 10 and ctx["at_or_above_pct"] == 100.0


def test_scores_are_counted_too_but_are_not_grades():
    """S&P 는 0-100 점수다 — 등급 서열이 없으니 숫자로 센다."""
    universe = rows(sp=["80", "43", "43", "10", "-"])
    ctx = build_context(universe, [rating("sp", "S&P", 43)])["by_agency"]["sp"]
    assert ctx["kind"] == "score" and ctx["rated"] == 4
    assert ctx["at_or_above"] == 3 and ctx["same_grade"] == 2


def test_unknown_grade_is_skipped_rather_than_guessed():
    universe = rows(kcgs=["A", "B"])
    assert build_context(universe, [rating("kcgs", "KCGS", "Z")])["by_agency"] == {}


def test_markdown_never_prints_a_top_n_percent_claim():
    d = {"distribution": {"year": 2025, "universe": 795,
                          **build_context(rows(kcgs=["A+", "A", "A", "B"]), [rating("kcgs", "KCGS", "A")], universe=795),
                          "reading_notes": READING_NOTES}}
    text = "\n".join(_distribution_lines(d))
    assert "상위" not in text.split("> ")[0]                          # 표에는 「상위 N%」가 없다
    assert "동점" in text and "「상위 N%」를 만들지 않는다" in text


async def test_ratings_payload_carries_the_distribution(krx_client):
    payload = await build_esg_ratings_payload("삼성전자", 2025, client=krx_client)
    dist = payload["data"].get("distribution")
    assert dist and dist["year"] == 2025
    assert "kcgs" in dist["by_agency"]
    assert dist["by_agency"]["kcgs"]["rated"] >= 1


async def test_distribution_failure_does_not_break_the_ratings(krx_client, monkeypatch):
    """분포는 곁들이는 정보다 — 못 구해도 등급 답변은 살아야 한다."""
    async def boom(*args, **kwargs):
        raise TimeoutError("포털 지연")
    monkeypatch.setattr(krx_client, "company_list", boom)
    payload = await build_esg_ratings_payload("삼성전자", 2025, client=krx_client)
    assert payload["status"] == "exact" and payload["data"]["ratings"]
    assert "distribution" not in payload["data"]
    assert any("등급 분포를 계산하지 못해" in w for w in payload["warnings"])
