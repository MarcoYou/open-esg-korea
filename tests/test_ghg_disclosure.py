"""GIR 명세서 ↔ 보고서 공시치 범위 정렬 (4a).

발췌 문구는 2026-09-08 실호출에서 그대로 가져온 것이다(현대차 2025·SK하이닉스 2025 보고서).
파서가 아니라 **판정 규칙**을 시험하므로 PDF 가 아니라 쪽 텍스트를 직접 넣는다.
"""

from __future__ import annotations

from open_esg_korea.services.ghg import build_ghg_emissions_payload
from open_esg_korea.services.ghg_disclosure import READING_NOTES, basis_summary, collect_scope_mentions
from open_esg_korea.tools.ghg_emissions import _disclosure_lines

# 현대차 2025 보고서 p39·p135 — 같은 2,097,809 인데 한쪽은 방식, 한쪽은 경계를 밝힌다.
HYUNDAI_39 = ("Scope 2 (지역 기반) 1,853,813 1,831,531 1,726,829 Scope 2 (시장 기반)2) 1,684,120 "
              "1,579,161 1,417,987 Scope 1+2 합계3) 2,404,069 2,275,751 2,097,809")
HYUNDAI_135 = ("국내 전 사업장과 11개 해외법인의 온실가스 배출량을 합산하여 공시하고 있습니다. "
               "온실가스 배출량(Scope 1+2, tCO2-eq): 2,097,809")
# SK하이닉스 2025 보고서 p87 검증의견서 — 국내·NF3 선택항목이 함께 나온다.
HYNIX_87 = ("직접배출(Scope 1) 1,515,830 1,190,629 534 88 2,707,081 간접배출(Scope 2) 1,439,806 691,152 "
            "4,116 1,456 2,136,530 Optional Information (NF3 사용) 503,433 370,360 - - 873,793 "
            "합계 3,459,068 2,252,141 4,650 1,543 5,717,404 검증범위 · SK하이닉스㈜ 국내사업장 2024년 온실가스 배출량")
NO_NUMBER = "Scope 1 배출량을 최소화하기 위해 다방면으로 노력하고 있습니다. 폐열 활용을 확대합니다."


def test_mentions_need_a_number_not_just_the_word():
    """서술만 있는 대목은 비교에 쓸 수 없다 — 수치가 함께 있는 곳만 집는다."""
    assert collect_scope_mentions([NO_NUMBER]) == []
    assert collect_scope_mentions([HYUNDAI_39])


def test_scope_1_plus_2_is_not_mistaken_for_scope_1():
    """「Scope 1+2」를 「Scope 1」로 읽으면 두 배 가까이 틀린다 — 합계 표기를 먼저 맞춘다."""
    kinds = {m["kind"] for m in collect_scope_mentions([HYUNDAI_39])}
    assert "scope12" in kinds and "scope1" not in kinds


def test_basis_axes_are_detected_from_the_wording():
    by_page = {m["page"]: m["basis"] for m in collect_scope_mentions([HYUNDAI_39, HYUNDAI_135])}
    assert set(by_page[1]) == {"지역기반", "시장기반"}      # 방식은 밝혔고 경계는 안 밝혔다
    assert set(by_page[2]) == {"글로벌", "국내"}            # 경계는 밝혔고 방식은 안 밝혔다


def test_optional_items_and_verification_scope_are_flagged():
    """NF3 포함 여부가 SK하이닉스에선 87만 톤을 가른다 — 축으로 잡아야 한다."""
    basis = collect_scope_mentions([HYNIX_87])[0]["basis"]
    assert "NF3" in basis and "국내" in basis


def test_unknown_basis_is_reported_as_unknown():
    """범위를 못 밝힌 발췌는 **빈 basis** 로 남긴다 — 임의로 「국내」라고 채우면 안 된다."""
    text = "Scope 1, 2 온실가스 배출량 2,097,809tCO2-eq 를 배출하였습니다."
    assert collect_scope_mentions([text])[0]["basis"] == []


def test_basis_summary_lists_pages_per_axis():
    axes = basis_summary(collect_scope_mentions([HYUNDAI_39, HYUNDAI_135, HYNIX_87]))
    assert axes["지역기반"] == [1] and axes["글로벌"] == [2] and axes["NF3"] == [3]
    assert "국내" in axes


def test_markdown_marks_unknown_basis_as_not_comparable():
    d = {"disclosure": {"report": {"year": "2025", "title": "보고서", "pdf": "u", "page_count": 3},
                        "mentions": collect_scope_mentions(["Scope 1+2 합계 2,097,809"]),
                        "basis_axes": {}, "reading_notes": READING_NOTES}}
    text = "\n".join(_disclosure_lines(d))
    assert "범위 불명" in text and "GIR 과 비교하지 말 것" in text


async def test_report_is_opt_in(krx_client, kind_client, gir_client):
    plain = await build_ghg_emissions_payload("삼성전자", client=krx_client, gir=gir_client)
    assert "disclosure" not in plain["data"]        # 기본은 보고서를 받지 않는다(느리다)


async def test_reading_notes_explain_the_range_not_the_gap(krx_client, kind_client, gir_client):
    """「값이 다르다」가 아니라 「범위가 다르다」로 읽히게 한다 — 실측이 그렇기 때문이다."""
    joined = " ".join(READING_NOTES)
    assert "같은 값을 다르게 센 것이 아니라" in joined
    assert "Scope 3 는 GIR 에 없다" in joined


# 현대차 2025 보고서 p115 — 합계와 개별이 한 표에 있고, 범위는 **표 아래 각주**에 적혀 있다.
HYUNDAI_115 = ("구분 단위 2022 2023 2024 비고 Scope 1+2 합계 tCO2-eq 2,404,069 2,275,751 2,097,809 "
               "Scope 1 tCO2-eq 719,949 696,590 679,822 Scope 2 tCO2-eq 1,684,120 1,579,161 1,417,987 "
               "시장 기반 기준 Scope 1+2 집약도 tCO2-eq/대 0.601 0.531 0.506 "
               "Scope 3 tCO2-eq 137,935,453 148,126,153 147,253,154 "
               "1) 환경 데이터의 보고 범위는 국내 전 사업장 및 해외 12개 생산법인이며, 모든 대당 집약도는 생산대수 기준")


def test_masking_the_total_does_not_hide_the_individual_rows():
    """「Scope 1+2」를 막되 같은 표의 별도 「Scope 1」·「Scope 2」 행은 살아 있어야 한다."""
    kinds = {m["kind"] for m in collect_scope_mentions([HYUNDAI_115])}
    assert kinds == {"scope12", "scope1", "scope2", "scope3"}


def test_basis_can_come_from_a_footnote_outside_the_snippet():
    """범위는 표 아래 각주에 적히는 일이 많다 — 보여줄 발췌보다 넓은 문맥에서 찾아야 한다."""
    m = next(m for m in collect_scope_mentions([HYUNDAI_115]) if m["kind"] == "scope12")
    assert {"글로벌", "국내", "시장기반"} <= set(m["basis"])
    assert "생산법인" not in m["snippet"]           # 각주는 발췌에 안 들어간다
