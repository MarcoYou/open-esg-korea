"""부록 표 행 후보 — 글자 좌표 fixture(실제 보고서 9쪽)로 파서를, 3쪽 PDF fixture 로 도구를 잰다. network 0.

글자 좌표 fixture 는 2026-09-24 공시 첨부 PDF 에서 뽑았다(`sr_words_*.json` 의 `source`). 한 쪽에 표가 좌우로 붙은 쪽,
머리가 두 겹·세 겹인 쪽, 행 이름이 값 줄 위·가운데에 따로 있는 쪽, 숫자를 가운데 맞춤한 쪽을 골랐다 — 파서를 고칠 때마다
틀렸던 모양들이다(실측 노트 21).
"""

from __future__ import annotations

import csv
import io
import json
import pathlib
import re

import pytest

from open_esg_korea.pdf import tables as T
from open_esg_korea.services.report_data import build_report_data_payload
from open_esg_korea.services.report_text import clear_cache
from open_esg_korea.tools.sustainability_report_data import CSV_COLUMNS, _csv, _render

FIX = pathlib.Path(__file__).parent / "fixtures"


def _page(code: str, page: int) -> list[T.Table]:
    data = json.loads((FIX / f"sr_words_{code}_p{page}.json").read_text())
    return T.parse_page(data["words"], data["page"])


def _row(tables: list[T.Table], label: str, parent: str | None = None) -> tuple[T.Table, T.Row]:
    for t in tables:
        for r in t.rows:
            if r.label == label and (parent is None or r.parent == parent):
                return t, r
    raise AssertionError(f"행 없음: {label}")


@pytest.fixture(autouse=True)
def _fresh_cache():
    clear_cache()
    yield
    clear_cache()


# ── 파서: 모양별 ─────────────────────────────────────────────────────────────
def test_side_by_side_tables_are_split_and_rows_land_on_their_years():
    """삼성전자 p70 — 왼쪽 에너지 표와 오른쪽 폐전자제품 표가 한 줄에 붙어 있다. 격자는 두 표를 한 행으로 이었다."""
    tables = _page("005930", 70)
    _, energy = _row(tables, "사업장 에너지 사용량")
    assert energy.values == {"2023": "36,399", "2024": "38,772", "2025": "40,249"} and energy.unit == "GWh"
    _, collected = _row(tables, "폐제품 누적 수거량")
    assert collected.values["2025"] == "7,544,747"
    assert all(r.status == "ok" for t in tables for r in t.rows)


def test_two_level_header_division_by_year():
    """삼성전자 p72 — 「2023년」 한 글자가 DX부문·DS부문 두 열 위에 걸친다. 각주 표지 「2)」 를 값으로 읽으면 이게 깨졌다."""
    tables = _page("005930", 72)
    _, scope1 = _row(tables, "Scope 1 배출량")
    assert scope1.values["2025·DS부문"] == "4,390" and scope1.values["2023·DX부문"] == "211"
    assert scope1.unit == "천 톤 CO₂e"
    _, energy = _row(tables, "사업장 에너지 사용량")
    assert energy.values["2025·DS부문"] == "36,081"


def test_label_above_a_unit_pair_and_domestic_overseas_columns():
    """LG에너지솔루션 p141 — 행 이름이 TJ·MWh 두 줄 위에 따로 있고, 해마다 국내·해외·전사(연결) 세 열이다."""
    tables = _page("373220", 141)
    t, tj = next((t, r) for t in tables for r in t.rows if r.label == "전력 사용량" and r.unit == "TJ")
    assert tj.label_from == "adjacent_line"
    assert tj.values["2025·전사(연결)"] == "37,661" and tj.values["2023·국내"] == "6,223"
    mwh = next(r for r in t.rows if r.label == "전력 사용량" and r.unit == "MWh")
    assert mwh.values["2025·국내"] == "769,141"


def test_label_between_a_unit_pair_and_a_category_line_under_the_years():
    """현대모비스 p137 — 이름이 TJ·MWh 쌍 **가운데**, 연도 줄과 하위 머리 사이에 「구분 단위」 줄, 빈 칸은 「~」."""
    tables = _page("012330", 137)
    _, tj = next((t, r) for t in tables for r in t.rows if r.label == "에너지 사용량" and r.unit == "TJ")
    assert tj.values["2025·합계"] == "7,032" and tj.values["2025·국내 자회사"] == "2,389"
    _, cost = next((t, r) for t in tables for r in t.rows if r.label == "보고연도(당기)")
    assert cost.values["2023·국내 자회사"] == "~"


def test_offset_neighbour_table_and_actual_vs_target_columns():
    """삼성생명 p131 — 오른쪽 에너지 표는 머리가 한 줄 위·두 줄로 갈렸고(2024 2025 / 2022 2023), 성과·목표 열이 있다.
    예전엔 오른쪽 아래 표가 왼쪽 표의 행 이름을 가져와 **검사를 통과한 채** 틀린 행을 만들었다."""
    tables = _page("032830", 131)
    _, financed = _row(tables, "금융배출량 (총계)")
    assert financed.values == {"2022": "3,872", "2023": "2,781", "2024": "2,771", "2025": "2,574"}
    for t in tables:
        for r in t.rows:
            if r.status == "ok":
                assert not any(ch.isdigit() and "," in tok for tok in r.label.split() for ch in tok), r.label


def test_three_level_company_headers_share_one_table():
    """HD한국조선해양 p158 — 회사명(HD한국조선해양·HD현대중공업·HD현대삼호) › 합병 이전/이후 › 연도 가 한 표다."""
    tables = _page("329180", 158)
    t, total = next((t, r) for t in tables for r in t.rows if r.label.startswith("온실가스 총 배출량(Scope 1+2)"))
    assert total.values["HD현대중공업·합병 이후·2025"] == "826,449"
    assert total.values["HD한국조선해양·2025"] == "8,441"
    assert total.values["HD현대삼호·2025"] == "272,844"


def test_centre_aligned_numbers():
    """SK p152 — 숫자를 가운데 맞춤했다. 오른쪽 끝으로 열을 잡으면 한 해가 두 열로 갈렸다."""
    tables = _page("034730", 152)
    _, total = next((t, r) for t in tables for r in t.rows if r.label == "합계" and r.unit == "tCO₂eq")
    assert total.values["2025"] == "19,608,833.9"


def test_target_column_is_named_on_the_year_line():
    """하나금융지주 p196 — 「2022 2023 2024 2025 2025 목표」. 표시 없는 2025 가 실적, 표시된 쪽이 목표다."""
    tables = _page("086790", 196)
    _, sbti = next((t, r) for t in tables for r in t.rows if r.label == "SBTi 기준" and r.parent.startswith("합계")) \
        if any(r.parent.startswith("합계") for t in tables for r in t.rows) else \
        next((t, r) for t in tables for r in t.rows if "69,897" in r.values.values())
    assert sbti.values["2025"] == "69,897" and sbti.values["2025·목표"] == "68,364"


# ── 검사: 조용히 틀린 값을 주지 않는다 ─────────────────────────────────────────
def _w(text, x0, x1, top):
    return {"text": text, "x0": x0, "x1": x1, "top": top, "bottom": top + 8}


def test_duplicate_column_heads_send_every_row_to_check():
    """한 해 아래 두 열을 가를 머리가 없으면 값을 싣지 않는다 — 어느 쪽이 실적인지 모르니까."""
    words = [_w("구분", 10, 30, 10), _w("2024", 100, 120, 10), _w("2024", 140, 160, 10),
             _w("배출량", 10, 40, 30), _w("1,000", 95, 120, 30), _w("2,000", 135, 160, 30),
             _w("사용량", 10, 40, 50), _w("3,000", 95, 120, 50), _w("4,000", 135, 160, 50)]
    tables = T.parse_page(words, 1)
    assert tables and all(r.status == "check" and not r.values for t in tables for r in t.rows)


def test_split_number_is_flagged():
    """숫자 하나가 글자 둘로 갈렸으면(틈 0.8pt 미만) 검사에 건다."""
    words = [_w("2024", 100, 120, 10), _w("2025", 140, 160, 10),
             _w("배출량", 10, 40, 30), _w("1,0", 100, 110, 30), _w("00", 110.3, 120, 30), _w("2,000", 135, 160, 30),
             _w("사용량", 10, 40, 50), _w("3,000", 95, 120, 50), _w("4,000", 135, 160, 50)]
    row = next(r for t in T.parse_page(words, 1) for r in t.rows if r.label == "배출량")
    assert row.status == "check" and any("붙어 있습니다" in p for p in row.problems)


@pytest.mark.parametrize("texts, label, unit, marks", [
    (["직접", "배출량(Scope", "1)"], "직접 배출량(Scope 1)", "", []),        # 괄호를 닫는 「1)」은 이름이다
    (["에너지", "사용량1)"], "에너지 사용량", "", ["1"]),                    # 붙은 표지는 뗀다
    (["Scope", "1", "배출량", "천", "톤", "CO₂e"], "Scope 1 배출량", "천 톤 CO₂e", []),
    (["중동/아프리카", "GWh"], "중동/아프리카", "GWh", []),                  # 빗금 든 행 이름을 단위로 거두지 않는다
    (["수료", "인원", "1)", "해외법인"], "수료 인원 해외법인", "", ["1"]),     # 가운데 낀 표지(분류 칸 + 항목)
    (["참석률1)", "사적금전대차"], "참석률 사적금전대차", "", ["1"]),
    (["(Scope", "1)", "배출량"], "(Scope 1) 배출량", "", []),                # 괄호를 닫는 가운데 「1)」은 남긴다
    (["3)", "ton/"], "", "ton/", ["3"]),                                   # 단위 앞 표지만 남으면 이름이 아니다
])
def test_label_unit_and_marks(texts, label, unit, marks):
    assert T._split_label(texts) == (label, unit, marks)


# ── 행 이름이 값 줄과 다른 줄에 있는 표 ──────────────────────────────────────────
def _grid(rows: list[tuple[str, str | None, float]]) -> list[dict]:
    """(이름, 2024 값 또는 None, 줄 높이) 목록 → 글자 좌표. 값이 None 이면 이름만 있는 줄. 2023 값은 「0」."""
    words = [_w("2023", 160, 180, 10), _w("2024", 200, 220, 10)]
    for name, value, top in rows:
        if name:
            words.append(_w(name, 10, 10 + 8 * len(name), top))
        if value is not None:
            words += [_w("ton", 110, 125, top), _w("0", 175, 180, top), _w(value, 195, 220, top)]
    return words


def test_labels_printed_below_their_rows_are_matched_from_the_named_row_down():
    """값 / 이름 / 값 / 이름 … — 줄마다 위·아래에 이름 줄이 있다. 거리(위 6.5 · 아래 5pt)로 고르면 틀린다는 게 핵심이
    아니라, 이름이 같은 줄에 있는 행 옆에서부터 차례로 정해진다(LG에너지솔루션 2024 오른쪽 표 모양)."""
    words = _grid([("LGESMI", "300", 30), ("", "10", 41.5), ("공업용수", None, 46.5),
                   ("", "290", 53), ("상수도", None, 58), ("", "5", 64.5), ("기타", None, 69.5)])
    rows = {r.label: r for t in T.parse_page(words, 1) for r in t.rows}
    assert rows["공업용수"].values["2024"] == "10" and rows["상수도"].values["2024"] == "290"
    assert rows["기타"].values["2024"] == "5"
    assert rows["공업용수"].label_from == "adjacent_line"


def test_alternating_labels_with_no_anchor_go_to_check():
    """이름 / 값 / 이름 / 값 / 이름 — 어느 행도 기댈 데가 없으면 고르지 않는다."""
    words = _grid([("가스", None, 30), ("", "10", 36), ("전기", None, 42), ("", "20", 48), ("스팀", None, 54)])
    rows = [r for t in T.parse_page(words, 1) for r in t.rows]
    assert rows and all(r.status == "check" and not r.values for r in rows)


def test_label_far_from_a_value_line_is_not_borrowed():
    """40pt 아래 쪽 번호 줄은 바로 위 이름 줄을 가져가지 않는다(LG에너지솔루션 2024 p120 의 「120」)."""
    words = _grid([("배출량", "10", 30), ("", "20", 42), ("용수", None, 47), ("", "120", 88)])
    rows = [r for t in T.parse_page(words, 1) for r in t.rows]
    assert next(r for r in rows if r.values.get("2024") == "20" or "20" in r.line.split()).label == "용수"
    assert all(r.status == "check" for r in rows if "120" in r.line.split())


def test_hangul_font_without_bbox_is_put_back_on_its_line():
    """글꼴 정보가 빠진 글꼴은 pdfplumber 가 글자 상자를 기준선 아래에 놓는다 — 기준선에서 다시 잡는다."""
    from open_esg_korea.pdf.extract import _broken_top
    size, baseline_y = 6.5, 400.0                            # PDF 좌표(아래에서 위로)
    broken = {"size": size, "upright": True, "matrix": (6.5, 0, 0, 6.5, 100, baseline_y),
              "y1": baseline_y - 0.3, "top": 200.3}           # 윗끝이 기준선 아래 — 깨진 글꼴
    normal = {"size": size, "upright": True, "matrix": (6.5, 0, 0, 6.5, 100, baseline_y),
              "y1": baseline_y + 4.5, "top": 195.5}           # 윗끝이 기준선 위 0.69 × 크기
    assert _broken_top(normal) is None
    assert _broken_top(broken) == pytest.approx(200.3 + (-0.3) - 0.7 * size)
    assert abs(_broken_top(broken) - normal["top"]) < 0.2   # 같은 줄이 된다


def test_font_realigned_page_keeps_labels_on_their_rows():
    """LG에너지솔루션 2024 p120 — 한글만 5pt 아래로 읽히던 쪽. 보정 뒤엔 이름이 제 줄에 있고, 세로로 쌓은 분류 칸
    (「대기/오염/물질/배출/관리」)은 상위 행이 되지 않으며, 쪽 아래 각주의 「(2021, 2022, 2023)」은 표 머리가 아니다."""
    rows = [(re.sub(r"\s", "", r.parent), re.sub(r"\s", "", r.label), r) for t in _page("373220_2024", 120)
            for r in t.rows]                                  # 낱말은 원래 좌표로 묶어 띄어쓰기가 빠지기도 한다
    get = lambda label, parent=None: next(r for p, lb, r in rows if lb == label and parent in (None, p))  # noqa: E731
    assert get("용수총취수량").values == {"2021": "7,914,555", "2022": "10,460,365", "2023": "10,934,429"}
    assert get("질소산화물(NOx)", "국내대기오염물질총배출량").values["2023"] == "33,142"
    intensity = get("용수총취수원단위")
    assert intensity.unit.replace(" ", "") == "ton/억원" and intensity.values["2021"] == "44.335"
    assert get("용수총사용량").values["2021"] == "4,979,730"
    assert not {p for p, _, _ in rows} & {"대기", "오염", "물질", "배출", "관리", "용수"}


def test_superscripts_next_to_units_and_values():
    """「m」에 붙은 작은 「3」은 단위(m3), 값에 붙은 작은 「4)」는 그 값의 각주다 — 둘 다 값 열 숫자가 아니다."""
    small = lambda text, x0, x1, top: {"text": text, "x0": x0, "x1": x1, "top": top, "bottom": top + 4}  # noqa: E731
    words = [_w("2023", 100, 120, 10), _w("2024", 140, 160, 10),
             _w("취수량", 10, 40, 30), _w("m", 60, 67, 30), small("3", 67, 69.5, 29),
             _w("85", 110, 120, 30), _w("36", 150, 160, 30), small("4)", 160.5, 164, 29),
             _w("방류량", 10, 40, 50), _w("m", 60, 67, 50), small("3", 67, 69.5, 49),
             _w("70", 110, 120, 50), _w("60", 150, 160, 50)]
    row = next(r for t in T.parse_page(words, 1) for r in t.rows if r.label == "취수량")
    assert (row.status, row.unit, row.values) == ("ok", "m3", {"2023": "85", "2024": "36"})
    assert "4" in row.marks


def test_mark_with_far_away_text_is_not_a_footnote_paragraph():
    """「2)」와 250pt 떨어진 쪽 옆 목차가 한 줄이 돼도 각주 문단으로 읽어 아래 행을 삼키지 않는다(삼성생명 p138)."""
    words = [_w("2023", 100, 120, 10), _w("2024", 140, 160, 10),
             _w("배출량", 10, 40, 30), _w("1,000", 95, 120, 30), _w("2,000", 135, 160, 30),
             _w("2)", 80, 86, 42), _w("ESG", 340, 360, 42), _w("Data", 362, 380, 42),
             _w("사용량", 10, 40, 54), _w("3,000", 95, 120, 54), _w("4,000", 135, 160, 54)]
    rows = {r.label: r for t in T.parse_page(words, 1) for r in t.rows}
    assert rows["사용량"].values == {"2023": "3,000", "2024": "4,000"}


# ── 도구 ────────────────────────────────────────────────────────────────────
async def test_tool_returns_data_section_tables(krx_client, kind_client):
    payload = await build_report_data_payload("삼성전자", year=2025)
    d = payload["data"]
    assert payload["status"] == "exact" and d["pages"] == [3, 3]
    assert d["counts"]["ok_rows"] > 10 and d["counts"]["values"] > 30
    rows = [r for t in d["tables"] for r in t["rows"]]
    energy = next(r for r in rows if r["label"] == "사업장 에너지 사용량")
    assert energy["values"]["2024·DS부문"] == "34,592"
    assert any("후보" in w for w in payload["warnings"])


async def test_find_narrows_to_matching_rows(krx_client, kind_client):
    payload = await build_report_data_payload("삼성전자", year=2025, find="재생 에너지")
    rows = [r for t in payload["data"]["tables"] for r in t["rows"]]
    assert rows and all("재생에너지" in (r["label"] + r["parent"]).replace(" ", "") or True for r in rows)
    assert all(any("재생에너지" in x.replace(" ", "") for x in (r["label"], r["parent"], t["title"]))
               for t in payload["data"]["tables"] for r in t["rows"])


async def test_csv_is_long_format_one_value_per_line(krx_client, kind_client):
    payload = await build_report_data_payload("삼성전자", year=2025)
    reader = list(csv.reader(io.StringIO(_csv(payload))))
    assert reader[0] == CSV_COLUMNS
    ok = [r for r in reader[1:] if r[CSV_COLUMNS.index("상태")] == "ok"]
    assert len(ok) == payload["data"]["counts"]["values"]
    assert all(r[CSV_COLUMNS.index("값")] and r[CSV_COLUMNS.index("연도")] for r in ok)


async def test_markdown_shows_tables_and_check_rows(krx_client, kind_client):
    text = _render(await build_report_data_payload("삼성전자", year=2025))
    assert "### 3쪽" in text and "| 행 | 단위 |" in text and "사업장 에너지 사용량" in text


async def test_page_outside_the_section_is_parsed_on_request(krx_client, kind_client):
    payload = await build_report_data_payload("삼성전자", year=2025, page="1-2")
    assert payload["status"] == "exact" and payload["data"]["pages"] == [1, 2]


async def test_too_wide_page_range_is_explained(krx_client, kind_client):
    payload = await build_report_data_payload("삼성전자", year=2025, page="1-20")
    assert payload["status"] == "no_data" and any("12쪽까지" in w for w in payload["warnings"])


async def test_no_data_section_says_so_and_points_to_other_tools(krx_client, kind_client, monkeypatch):
    from open_esg_korea.pdf import extract
    monkeypatch.setattr(extract, "data_section", lambda pages: [])
    payload = await build_report_data_payload("삼성전자", year=2025)
    assert payload["status"] == "no_data"
    assert any("못 찾았다" in w for w in payload["warnings"])


def test_csv_is_cut_at_a_page_boundary_and_says_where_to_continue(monkeypatch):
    """값이 너무 많으면 쪽 경계에서 끊고 마지막 줄에 이어 부를 쪽 범위를 적는다 — 대화에 60만 자를 붓지 않게."""
    from open_esg_korea.tools import sustainability_report_data as tool
    monkeypatch.setattr(tool, "_MAX_CSV_VALUES", 3)
    row = {"label": "a", "parent": "", "unit": "", "values": {"2025": "1", "2024": "2"}, "status": "ok",
           "marks": [], "line": "", "problems": []}
    payload = {"data": {"company": {"name": "x", "isu_cd": "000000"}, "report": {"year": 2026, "acpt_no": "1"},
                        "tables": [{"page": p, "title": "t", "columns": [{"key": "2025", "year": "2025"},
                                                                       {"key": "2024", "year": "2024"}],
                                    "rows": [row], "footnotes": {}} for p in (10, 11, 12)]}}
    lines = list(csv.reader(io.StringIO(_csv(payload))))
    assert [l[CSV_COLUMNS.index("쪽")] for l in lines[1:-1]] == ["10", "10"]      # 첫 쪽만(값 2개), 다음 쪽이면 4개
    assert lines[-1][CSV_COLUMNS.index("상태")] == "잘림" and 'page="11-12"' in lines[-1][-1]
