"""연도별 ESG 수치 — 보고서 여러 건의 부록 표 잇기(순수 함수)와 도구 전체 경로. network 0."""

from __future__ import annotations

import csv
import io

from open_esg_korea.services.esg_timeseries import _series_dict, build_esg_timeseries_payload, stitch
from open_esg_korea.services.report_text import clear_cache
from open_esg_korea.tools.esg_timeseries import CSV_COLUMNS, _csv, _render


def _table(page: int, years: list[str], rows: list[dict], boundary: str = "") -> dict:
    cols = [{"key": f"{boundary}·{y}" if boundary else y, "year": y, "path": [boundary, y] if boundary else [y],
             "right": 100.0 + 40 * i} for i, y in enumerate(years)]
    out = []
    for r in rows:
        values = {c["key"]: v for c, v in zip(cols, r["values"]) if v is not None}
        out.append({"label": r["label"], "unit": r.get("unit", "tCO2eq"), "marks": [], "indent": 0.0,
                    "values": values if r.get("status", "ok") == "ok" else {}, "status": r.get("status", "ok"),
                    "problems": [], "line": "", "label_from": "same_line", "parent": r.get("parent", "")})
    return {"page": page, "title": "온실가스 배출량", "columns": cols, "rows": out, "footnotes": {}, "header_problems": []}


def _report(year: str, tables: list[dict]) -> dict:
    return {"year": year, "acpt_no": f"{year}0601000001", "tables": tables}


def test_rows_are_stitched_across_reports_and_restatements_are_marked():
    new = _report("2026", [_table(140, ["2023", "2024", "2025"],
                                  [{"label": "Scope 1 배출량", "values": ["100", "110", "120"]}])])
    old = _report("2025", [_table(130, ["2022", "2023", "2024"],
                                  [{"label": "Scope 1 배출량 1)", "values": ["90", "100", "105"]}])])
    [s] = stitch([new, old])                                   # 각주 표지·공백은 무시하고 잇는다
    d = _series_dict(s)
    assert d["values"] == {"2022": "90", "2023": "100", "2024": "110", "2025": "120"}
    assert d["sources"]["2024"]["report_year"] == "2026" and d["sources"]["2022"]["report_year"] == "2025"
    assert list(d["restated"]) == ["2024"]                     # 105 → 110: 최신 보고서 값을 보이고 이전 값을 함께
    assert [p["value"] for p in d["restated"]["2024"]] == ["110", "105"]


def test_different_boundary_or_unit_is_a_different_series():
    rep = _report("2026", [_table(140, ["2024", "2025"], [{"label": "배출량", "values": ["1", "2"]}], boundary="국내"),
                           _table(141, ["2024", "2025"], [{"label": "배출량", "values": ["3", "4"]}], boundary="해외"),
                           _table(142, ["2024", "2025"], [{"label": "배출량", "unit": "%", "values": ["5", "6"]}])])
    got = {(s.boundary, s.unit): _series_dict(s)["values"] for s in stitch([rep])}
    assert got == {("국내", "tCO2eq"): {"2024": "1", "2025": "2"}, ("해외", "tCO2eq"): {"2024": "3", "2025": "4"},
                   ("", "%"): {"2024": "5", "2025": "6"}}


def test_same_name_twice_in_one_report_is_not_stitched():
    """사업장별 표에서 「공업용수」가 사업장마다 나오면 서로 다른 행이다 — 다른 해 보고서와 잇지 않는다."""
    new = _report("2026", [_table(120, ["2024", "2025"], [{"label": "공업용수", "unit": "ton", "values": ["1", "2"]},
                                                          {"label": "공업용수", "unit": "ton", "values": ["3", "4"]}])])
    old = _report("2025", [_table(110, ["2023", "2024"], [{"label": "공업용수", "unit": "ton", "values": ["9", "1"]}])])
    series = stitch([new, old])
    assert [s.ambiguous for s in series].count(True) == 2
    assert all(len(s.points) == 2 for s in series if s.ambiguous)       # 제 보고서 값만
    assert not any(s.restated(y) for s in series for y in s.points)     # 가짜 「수정됨」을 만들지 않는다


def test_rows_that_failed_checks_are_left_out():
    rep = _report("2026", [_table(140, ["2024", "2025"], [{"label": "배출량", "values": ["1", "2"], "status": "check"}])])
    assert stitch([rep]) == []


def test_markdown_and_csv_show_restatements_and_sources():
    new = _report("2026", [_table(140, ["2024", "2025"], [{"label": "배출량", "values": ["110", "120"]}])])
    old = _report("2025", [_table(130, ["2023", "2024"], [{"label": "배출량", "values": ["100", "105"]}])])
    payload = {"status": "exact", "subject": "삼성전자", "warnings": [], "source": {}, "license": "", "next_actions": [],
               "tool": "esg_timeseries",
               "data": {"company": {"name": "삼성전자", "isu_cd": "005930"}, "find": "",
                        "reports": [{"year": "2026", "acpt_no": "20260601000001", "title": "보고서"}],
                        "years": ["2023", "2024", "2025"], "series": [_series_dict(s) for s in stitch([new, old])],
                        "counts": {"series": 1, "all_series": 1, "restated_points": 1, "reports_used": 2},
                        "gir": {"status": "exact", "history": [{"year": "2024", "emissions_tco2eq": 1000.0,
                                                                  "energy_tj": 20.0}], "note": "GIR"}}}
    md = _render(payload)
    assert "110 ✎" in md and "105(2025년 보고서)" in md and "GIR 명세서" in md
    rows = list(csv.DictReader(io.StringIO(_csv(payload))))
    assert list(rows[0]) == CSV_COLUMNS
    y2024 = [r for r in rows if r["연도"] == "2024" and r["출처"] == "보고서"]
    assert {(r["값"], r["최신보고서값"]) for r in y2024} == {("110", "Y"), ("105", "")}
    assert any(r["출처"] == "GIR 명세서" and r["값"] == "1000.0" for r in rows)


async def test_tool_path_reads_reports_and_says_what_it_could_not_stitch(krx_client, kind_client):
    clear_cache()
    payload = await build_esg_timeseries_payload("삼성전자", reports=2)
    d = payload["data"]
    assert payload["status"] in ("exact", "no_data")
    assert [r["year"] for r in d["reports"]] and all("year" in r for r in d["reports"])
    assert any("물어본 지금" in w for w in payload["warnings"])     # 저장해 둔 데이터가 아니라고 말한다
    assert "gir" in d and "note" in d["gir"]
    clear_cache()
