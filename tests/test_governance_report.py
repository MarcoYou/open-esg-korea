"""기업지배구조보고서 원문 파서 — 원칙 답변·서식 표·미준수 사유.

fixture 는 2026-09-07 KIND 실호출 스냅샷이다. 삼성전자 본문은 원칙 3개(1-1·4-4·7-2)만 남긴 subset —
28개 전부는 5.7MB 라 저장소에 넣지 않는다. 「원칙 28개」는 실호출로 확인했다(스모크는 로컬에서만).
"""

from __future__ import annotations

import pathlib

from open_esg_korea.krx import codes
from open_esg_korea.services.governance_report import (
    INDICATOR_CONCEPT, parse_grid, parse_indicators, parse_principles, parse_report, parse_tables, text_of,
)

FIX = pathlib.Path(__file__).parent / "fixtures"
SAMSUNG = (FIX / "kind_gov_005930_2025_subset.html").read_text(encoding="utf-8")
KB = (FIX / "kind_gov_105560_2025.html").read_text(encoding="utf-8")


def test_principle_number_section_code_and_answer():
    principles = {p["no"]: p for p in parse_principles(SAMSUNG)}
    assert set(principles) == {"1-1", "4-4", "7-2"}
    p = principles["4-4"]
    assert p["section"] == "304400" and p["core"] == 4          # OPM 의 절 코드 체계와 같다
    assert p["text"].startswith("기업가치의 훼손 또는 주주권익의 침해에 책임이 있는 자를")
    assert p["answer"].startswith("당사는 임원의 선임시 주주가치 제고를 위한")
    assert "상기 세부원칙에 대한 준수여부" not in p["answer"]    # 서식 안내문은 답변이 아니다


def test_deficiency_reason_comes_from_the_principle_not_the_indicator_note():
    """「왜 미준수인가」는 지표 표의 비고가 아니라 원칙 안의 「미진한 부분 및 그 사유」에 있다.

    삼성전자 2025 는 비고 15칸이 전부 비어 있고, 사유는 7-2 등 원칙 블록에만 적혀 있다.
    """
    principles = {p["no"]: p for p in parse_principles(SAMSUNG)}
    assert "영업 상의 비밀" in principles["7-2"]["notes"]["deficiency"]
    assert principles["7-2"]["notes"]["plan"].endswith("검토하도록 하겠습니다.")
    assert principles["4-4"]["notes"] == {}
    assert all(not i["note"] for i in parse_indicators(SAMSUNG))


def test_only_krx_form_tables_are_returned():
    """`aclass="krx-cg_…"` 인 표만 서식 표다 — 회사 자유편집 표는 열이 제각각이라 돌려주지 않는다."""
    tables = parse_tables(SAMSUNG)
    assert all(t["concept"].startswith("krx-cg_") for t in tables)
    assert {t["no"] for t in tables if t["no"]} == {"1-1-1", "4-4-1", "7-2-1"}
    assert next(t for t in tables if t["no"] == "7-2-1")["principle"] == "7-2"
    assert next(t for t in tables if t["concept"] == INDICATOR_CONCEPT)["principle"] is None


def test_multi_row_header_is_expanded_so_columns_line_up():
    """출석률 표의 머리는 3단으로 겹쳐 있다 — 펼치지 않으면 열이 어긋난다."""
    table = next(t for t in parse_tables(SAMSUNG) if t["no"] == "7-2-1")
    assert table["title"] == "최근 3년간 이사 출석률 및 안건 찬성률"
    widths = {len(row) for row in table["header"]} | {len(row) for row in table["rows"]}
    assert widths == {11}
    assert table["header"][0][3] == "출석률 (%)" and table["header"][-1][4] == "당해연도"
    assert table["rows"][0][:2] == ["김기남", "사내이사(Inside)"]


def test_key_indicators_and_compliance_rate():
    report = parse_report(SAMSUNG, form=codes.KIND_FORM_GOV_REPORT)
    assert report["compliance_rate"] == 86.7
    indicators = report["indicators"]
    assert len(indicators) == 15
    assert indicators[0]["label"] == "주주총회 4주 전에 소집공고 실시"
    assert [i["label"] for i in indicators if i["current"] == "X"] == ["현금 배당관련 예측가능성 제공", "집중투표제 채택"]


def test_report_header_carries_company_and_disclosure_period():
    """2025 년에 낸 보고서의 공시대상 기간은 2024 년이다 — 연도를 접수일로 착각하면 안 된다."""
    report = parse_report(SAMSUNG, form=codes.KIND_FORM_GOV_REPORT)
    assert report["company_name"] == "삼성전자 주식회사"
    assert (report["period_start"], report["period_end"]) == ("2024-01-01", "2024-12-31")


def test_financial_company_annual_report_has_no_principles():
    """금융회사는 연차보고서로 갈음한다 — 본문은 안내문뿐이라 파싱할 원칙이 없다(미준수가 아니다)."""
    report = parse_report(KB, form=codes.KIND_FORM_ANNUAL_REPORT)
    assert report["kind"] == "annual_report"
    assert report["principles"] == [] and report["tables"] == [] and report["indicators"] == []


def test_unreadable_body_is_unknown_not_zero_compliance():
    """파싱 0건은 「읽지 못함」이지 「0개 준수」가 아니다 — 값을 지어내지 않는다."""
    report = parse_report("<html><body>Access Denied</body></html>")
    assert report["kind"] == "unknown"
    assert report["principles"] == [] and report["compliance_rate"] is None


def test_placeholder_answers_are_empty_not_content():
    html = ('<div id="DetailedPrinciple_9-9"><p class="toc-level1 SECTION-1">'
            '<span class="toc-level1">[309900] (세부원칙 9-9) - 시험용 원칙</span></p>'
            '<span class="concept-label">상기 세부원칙에 대한 준수여부를 간략하게 기술한다. (100자 이내)</span>'
            '<table><tbody><tr><td class="single-textbox" value="해당사항없음">해당사항없음</td></tr></tbody></table>'
            "</div>")
    assert parse_principles(html)[0]["answer"] == ""


def test_rowspan_and_colspan_quirks_of_the_krx_export():
    """서식 내보내기가 `rowspan=""`·`colspan="0"` 을 쓴다 — 둘 다 1 칸이다."""
    html = ('<table class="fact-table"><thead><tr><th rowspan="">가</th><th colspan="0">나</th></tr></thead>'
            '<tbody><tr><th>다</th><td>라</td></tr></tbody></table>')
    header, body = parse_grid(html)
    assert header == [["가", "나"]] and body == [["다", "라"]]


def test_text_keeps_punctuation_attached():
    assert text_of("<p>공개하지 못하고 있었습니다<span>.</span></p>") == "공개하지 못하고 있었습니다."
