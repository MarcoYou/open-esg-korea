"""지속가능경영보고서 PDF 본문 — 추출·검색·발췌·캐시·실패.

fixture 는 삼성전자 2025 보고서에서 **3쪽만 뽑은 진짜 PDF**(343KB)다: 표지 · 서술(자간이 벌어진 쪽) ·
Facts & Figures 수치 표. 합성 PDF 로는 한글 자간·표 문제를 재현할 수 없어 실물 일부를 쓴다.
"""

from __future__ import annotations

import pathlib

import pytest

from open_esg_korea.pdf import extract
from open_esg_korea.services.report_text import (
    build_report_text_payload, cache_stats, clear_cache, load_pages,
)
from open_esg_korea.tools.sustainability_report_text import _render

FIX = pathlib.Path(__file__).parent / "fixtures"
PDF = (FIX / "sr_005930_2025_3pages.pdf").read_bytes()
PDF_URL = ("https://kind.krx.co.kr/external/2025/06/27/000633/20250627000755/"
           "%EC%82%BC%EC%84%B1%EC%A0%84%EC%9E%90%20%EC%A7%80%EC%86%8D%EA%B0%80%EB%8A%A5"
           "%EA%B2%BD%EC%98%81%EB%B3%B4%EA%B3%A0%EC%84%9C_2025.pdf")


@pytest.fixture(autouse=True)
def _fresh_cache():
    clear_cache()
    yield
    clear_cache()


# ── 추출 계층 (네트워크 없음) ──────────────────────────────────────────────────
def test_pages_come_out_and_numbers_are_not_broken():
    """pypdf 는 `567 ,056` 처럼 숫자 안에 공백을 넣는다 — 틀린 값을 보여주면 안 되므로 이걸 지킨다."""
    pages = extract.page_texts(PDF)
    assert len(pages) == 3
    assert "567,056" in pages[2] and "567 ,056" not in pages[2]


def test_search_ignores_spacing_because_the_pdf_has_it_baked_in():
    """원문이 자간을 벌려 조판해 「재생 에너지」처럼 띄어져 있다 — 공백을 무시하지 않으면 0건이 된다."""
    pages = extract.page_texts(PDF)
    assert extract.search(pages, "재생에너지")          # 붙여 써도
    assert extract.search(pages, "재 생 에 너 지")       # 띄어 써도 같은 곳을 찾는다


def test_snippet_is_the_original_wording_not_the_squashed_one():
    hits = extract.search(extract.page_texts(PDF), "재생에너지")
    snippet = hits[0]["snippets"][0]
    assert "재생에너지 사용량" in snippet or "재생에너지 전환율" in snippet
    assert "  " not in snippet                       # 발췌는 한 줄로 정리해서 준다


def test_layout_mode_keeps_the_table_columns():
    """표를 보여줄 땐 열 정렬을 살린다 — 평문이면 어느 값이 어느 해인지 알 수 없다."""
    text = extract.page_layout(PDF, 3)
    line = next(l for l in text.split("\n") if "사업장 에너지 사용량" in l)
    assert "4,327" in line and "30,850" in line      # 같은 줄에 그 행의 값이 모여 있다


def test_missing_page_is_an_error_not_an_empty_string():
    with pytest.raises(extract.PdfReadError):
        extract.page_layout(PDF, 99)


def test_broken_bytes_are_a_read_error_not_a_crash():
    with pytest.raises(extract.PdfReadError):
        extract.page_texts(b"not a pdf at all")


def test_scanned_pdf_is_detected_as_unreadable_not_empty():
    """글자가 없는 PDF 는 「내용이 없다」가 아니라 「우리가 못 읽는다」다."""
    assert extract.looks_scanned(["", "  ", ""]) is True
    assert extract.looks_scanned(extract.page_texts(PDF)) is False


# ── 서비스·도구 ──────────────────────────────────────────────────────────────
async def test_overview_gives_the_table_of_contents(krx_client, kind_client):
    payload = await build_report_text_payload("삼성전자", year=2025)
    data = payload["data"]
    assert data["mode"] == "overview" and data["page_count"] == 3
    assert "Facts & Figures" in data["toc"]
    assert data["attachment"]["name"].endswith(".pdf")


async def test_find_reports_pages_and_snippets(krx_client, kind_client):
    payload = await build_report_text_payload("삼성전자", year=2025, find="재생에너지")
    data = payload["data"]
    assert data["match_pages"] == [3] and data["total_hits"] >= 2
    assert "재생에너지" in data["matches"][0]["snippets"][0]


async def test_no_hit_says_not_found_rather_than_absent(krx_client, kind_client):
    payload = await build_report_text_payload("삼성전자", year=2025, find="존재하지않는표현")
    assert payload["data"]["match_pages"] == []
    assert any("「없다」고 단정하지 마세요" in w for w in payload["warnings"])


async def test_page_mode_is_aligned_and_warns_about_flattened_tables(krx_client, kind_client):
    payload = await build_report_text_payload("삼성전자", year=2025, page=3)
    data = payload["data"]
    assert data["aligned"] is True
    assert "사업장 에너지 사용량" in data["page_text"]
    assert any("수치를 기계적으로 뽑지 않습니다" in w for w in payload["warnings"])


async def test_page_out_of_range_is_no_data(krx_client, kind_client):
    payload = await build_report_text_payload("삼성전자", year=2025, page=99)
    assert payload["status"] == "no_data"
    assert any("99쪽은 이 보고서에 없습니다" in w for w in payload["warnings"])


async def test_second_question_does_not_hit_the_network(krx_client, kind_client):
    await build_report_text_payload("삼성전자", year=2025, find="재생에너지")
    calls = kind_client.calls
    await build_report_text_payload("삼성전자", year=2025, find="폐기물")
    assert kind_client.calls == calls                 # 페이지 텍스트가 캐시에 있다
    assert cache_stats()["documents"] == 1


async def test_pdf_bytes_are_not_kept_as_the_document_cache(krx_client, kind_client):
    """캐시에 남는 것은 텍스트뿐이다 — 4~80MB 짜리 원본을 들고 있지 않는다."""
    await load_pages(PDF_URL, kind_client)
    assert cache_stats()["chars"] < 100_000           # 3쪽 텍스트는 수천 자
    assert cache_stats()["documents"] == 1


async def test_company_without_an_attachment_is_no_data(krx_client, kind_client, monkeypatch):
    from open_esg_korea.services import report_text
    monkeypatch.setattr(report_text, "_pick_attachment", lambda atts: None)
    payload = await build_report_text_payload("삼성전자", year=2025)
    assert payload["status"] == "no_data"
    assert any("회사 사이트에만 올렸을 수 있습니다" in w for w in payload["warnings"])


async def test_korean_attachment_wins_when_both_languages_are_filed():
    """SK하이닉스처럼 국·영문 2건이 붙는 회사가 있다 — 국문을 고른다."""
    from open_esg_korea.services.report_text import _pick_attachment
    picked = _pick_attachment([{"name": "SK hynix Sustainability Report 2025_ENG.pdf", "url": "e"},
                               {"name": "SK하이닉스 지속가능경영보고서 2025_KOR.pdf", "url": "k"}])
    assert picked["url"] == "k"


async def test_markdown_shows_snippets_and_the_source_pdf(krx_client, kind_client):
    text = _render(await build_report_text_payload("삼성전자", year=2025, find="재생에너지"))
    assert "### 3쪽" in text and "재생에너지" in text
    assert "원문 PDF: [삼성전자 지속가능경영보고서_2025.pdf]" in text
    assert "공시 원문" in text                          # 평가기관 고지가 아니라 공시 고지


# ── 격자 모드 (실험적) ────────────────────────────────────────────────────────
def test_grid_recovers_the_left_hand_table_rows():
    """글자 정렬로 열을 가르면 행 라벨·단위·값이 한 줄에 모인다 — 괘선이 없어 선 기반 검출은 0개다.

    다만 이 쪽엔 표가 **좌우로 두 개** 놓여 있어 한 행에 두 표가 이어진다 — 격자를 믿기 전에
    알아야 할 한계다(그래서 `table=True` 는 기본값이 아니다).
    """
    rows = [r for g in extract.page_tables(PDF, 3) for r in g]
    row = next(r for r in rows if r[0].startswith("재생에너지") and "전환율" in " ".join(r))
    filled = [c for c in row if c]
    assert filled[:9] == ["재생에너지", "전환율", "%", "93.1", "23.2", "93.4", "24.3", "93.4", "24.8"]
    # 오른쪽 표가 같은 행에 이어 붙는다 — 심지어 「폐기물 처리량」이 `폐` + `기물 처리량` 으로 갈린다.
    assert len(filled) > 9 and "".join(filled[9:]).startswith("폐기물")


def test_split_numbers_are_flagged_not_served_silently():
    """열을 잘못 자르면 `307,325` 가 `3` + `07,325` 로 갈린다. 고칠 순 없어도 짚어는 준다."""
    flat = extract.page_texts(PDF)[2]
    grids = extract.page_tables(PDF, 3)
    flagged = {grids[i][r][c] for i, g in enumerate(grids) for r, c in extract.suspect_cells(g, flat)}
    assert "07,325" in flagged                       # 평문에는 `307,325` 로만 있는 조각
    assert "329,861" not in flagged                  # 멀쩡한 값은 짚지 않는다


def test_intact_values_are_never_flagged():
    flat = extract.page_texts(PDF)[2]
    for grid in extract.page_tables(PDF, 3):
        for r, c in extract.suspect_cells(grid, flat):
            assert grid[r][c] not in flat.split()    # 평문 토큰이면 의심할 이유가 없다


async def test_grid_is_opt_in_and_comes_with_a_warning(krx_client, kind_client):
    plain = await build_report_text_payload("삼성전자", year=2025, page=3)
    assert "tables" not in plain["data"]             # 기본은 격자를 만들지 않는다

    payload = await build_report_text_payload("삼성전자", year=2025, page=3, table=True)
    data = payload["data"]
    assert data["tables"] and data["suspect_cells"] > 0
    assert any("검증되지 않은 실험 결과" in w for w in payload["warnings"])


async def test_markdown_marks_suspect_cells(krx_client, kind_client):
    text = _render(await build_report_text_payload("삼성전자", year=2025, page=3, table=True))
    assert "### 격자 (실험적" in text
    assert "⚠07,325" in text


# ── 데이터 장 · 여백 정리 (네트워크 없음) ─────────────────────────────────────────
def _numbers_page(years: str = "2023 2024 2025") -> str:
    return years + " " + " ".join(f"{100 + i},{500 + i}" for i in range(30))


def test_data_section_finds_the_numbers_page_in_the_fixture():
    """표지·서술·수치 표 3쪽 중 수치 표 쪽만 데이터 장이다."""
    assert extract.data_section(extract.page_texts(PDF)) == [3]


def test_data_section_bridges_small_gaps_and_picks_the_longest_run():
    """각주·설명 쪽 한두 장이 끼어도 한 장으로 잇고, 앞쪽 하이라이트 쪽 같은 외톨이는 고르지 않는다."""
    narrative, numbers = "서술 문단", _numbers_page()
    pages = [narrative, numbers] + [narrative] * 6 + [numbers, narrative, numbers, numbers, narrative, narrative, numbers]
    #        1          2           3..8            9        10         11       12       13         14         15
    assert extract.data_section(pages) == list(range(9, 16))


def test_data_section_needs_several_years_not_just_numbers():
    """숫자만 많고 연도가 하나뿐인 쪽(재무제표 「제 27 기」, 보고서 머리글 「2025 …」)은 ESG 수치 표 쪽이 아니다."""
    assert extract.data_section([_numbers_page(years="")]) == []
    assert extract.data_section([_numbers_page(years="2025 NAVER INTEGRATED REPORT 제 27 기")]) == []
    assert extract.data_section(["서술"] * 5) == []            # 「없다」가 아니라 「이 신호로 못 찾았다」


def test_data_section_reads_pdfs_that_come_out_column_by_column():
    """NAVER 2025 통합보고서는 글자가 열 단위로 나온다(2023 열 값 전부 → 2024 열 …) — 연도가 나란하지 않아도 잡는다.

    예전 규칙(「2023 2024 2025 가 나란히」)으로는 데이터 장을 못 찾고 94쪽 한 장을 골랐다(2026-09-24).
    """
    column = "\n".join(f"{100 + i},{500 + i}" for i in range(10))
    page = f"에너지 총사용량\n단위 2023\n{column}\n2024\n{column}\n2025\n{column}"
    assert extract.is_data_page(page)
    assert extract.data_section(["서술", page, page, "서술"]) == [2, 3]


def test_compact_layout_keeps_columns_and_drops_only_margins():
    raw = "      \n      a     1    2      \n      bb    3    4\n\n\n   \n      c     5    6   \n\n"
    lines = extract.compact_layout(raw).split("\n")
    assert lines == ["a     1    2", "bb    3    4", "", "c     5    6"]
    assert lines[0].index("1") == lines[1].index("3")          # 줄 안의 칸 간격은 그대로 — 열 정렬 유지


def test_layout_page_has_no_blank_margins():
    lines = extract.page_layout(PDF, 3).split("\n")
    assert all(line == line.rstrip() for line in lines)
    assert min(len(l) - len(l.lstrip()) for l in lines if l.strip()) == 0


# ── 동시성: 원본이 밀려도 데이터 장은 정렬돼 나온다 ───────────────────────────────
def _evict_pdf_bytes() -> None:
    """다른 대화가 다른 보고서를 열어 원본 자리를 가져간 상황."""
    from open_esg_korea.services import report_text
    report_text._keep_bytes("https://kind.krx.co.kr/external/other.pdf", b"%PDF-other")


async def test_data_section_page_stays_aligned_after_the_pdf_bytes_are_gone(krx_client, kind_client):
    """30개사 동시 실행에서 쪽 보기 133회 중 100회가 평문으로 나갔다 — 원본 한 칸을 서로 밀어냈기 때문이다."""
    await build_report_text_payload("삼성전자", year=2025, find="재생에너지")
    _evict_pdf_bytes()
    calls = kind_client.calls
    payload = await build_report_text_payload("삼성전자", year=2025, page=3)
    assert payload["data"]["aligned"] is True
    assert payload["data"]["data_section"] == [3, 3]
    assert kind_client.calls == calls                 # 처음 받을 때 떠 둔 정렬 텍스트 — 다시 받지 않는다
    assert cache_stats()["aligned_pages"] >= 1


async def test_other_pages_are_refetched_for_alignment_not_served_flat(krx_client, kind_client):
    await build_report_text_payload("삼성전자", year=2025, find="재생에너지")
    _evict_pdf_bytes()
    calls = kind_client.calls
    payload = await build_report_text_payload("삼성전자", year=2025, page=2)
    assert payload["data"]["aligned"] is True
    assert kind_client.calls > calls                  # 데이터 장 밖이라 원본을 다시 받았다(25MB 이하)
    assert not any("평문으로" in w for w in payload["warnings"])


async def test_big_document_fallback_says_why_and_points_to_the_aligned_section(krx_client, kind_client,
                                                                                monkeypatch):
    """평문으로 줄 때는 **진짜 이유**를 말한다 — 예전엔 원본이 밀린 경우도 「문서가 커서」라고 했다."""
    from open_esg_korea.services import report_text
    monkeypatch.setattr(report_text, "_BYTES_MAX", 1000)          # fixture(343KB)를 「큰 문서」로 만든다
    flat = await build_report_text_payload("삼성전자", year=2025, page=2)
    assert flat["data"]["aligned"] is False
    reason = next(w for w in flat["warnings"] if "평문으로" in w)
    assert "MB 라 정렬용으로 다시 받지 않았습니다" in reason and "데이터 장(3쪽)은" in reason
    aligned = await build_report_text_payload("삼성전자", year=2025, page=3)
    assert aligned["data"]["aligned"] is True                    # 데이터 장은 크기와 무관하게 정렬돼 있다


async def test_refetch_failure_is_reported_as_a_refetch_failure(krx_client, kind_client, monkeypatch):
    from open_esg_korea.krx.kind import KindClientError
    await build_report_text_payload("삼성전자", year=2025, find="재생에너지")
    _evict_pdf_bytes()

    async def refuse(url, **_):
        raise KindClientError("KIND 응답 없음")
    monkeypatch.setattr(kind_client, "file", refuse)
    payload = await build_report_text_payload("삼성전자", year=2025, page=2)
    assert payload["data"]["aligned"] is False
    assert any("정렬용 원본을 다시 받지 못했습니다" in w for w in payload["warnings"])


# ── 쪽 범위 ──────────────────────────────────────────────────────────────────
async def test_page_range_returns_each_page(krx_client, kind_client):
    payload = await build_report_text_payload("삼성전자", year=2025, page="2-3")
    data = payload["data"]
    assert [v["page"] for v in data["page_views"]] == [2, 3]
    assert all(v["aligned"] for v in data["page_views"])
    assert "page_text" not in data                    # 한 쪽짜리 예전 키는 한 쪽일 때만
    text = _render(payload)
    assert "### 2쪽" in text and "### 3쪽" in text


async def test_page_given_as_a_string_number_works_like_an_int(krx_client, kind_client):
    payload = await build_report_text_payload("삼성전자", year=2025, page="3")
    assert payload["data"]["aligned"] is True and "사업장 에너지 사용량" in payload["data"]["page_text"]


async def test_page_range_past_the_end_is_clipped_and_says_so(krx_client, kind_client):
    payload = await build_report_text_payload("삼성전자", year=2025, page="3-5")
    assert [v["page"] for v in payload["data"]["page_views"]] == [3]
    assert any("전체 3쪽이라 3쪽만 보여줍니다" in w for w in payload["warnings"])


@pytest.mark.parametrize("page, message", [("1-9", "한 번에 5쪽까지"), ("3-2", "시작(3쪽)보다 앞"),
                                           ("abc", "쪽 번호(73) 또는 범위")])
async def test_bad_page_argument_is_explained_not_guessed(krx_client, kind_client, page, message):
    payload = await build_report_text_payload("삼성전자", year=2025, page=page)
    assert payload["status"] == "no_data"
    assert any(message in w for w in payload["warnings"])


async def test_grid_needs_a_single_page(krx_client, kind_client):
    payload = await build_report_text_payload("삼성전자", year=2025, page="2-3", table=True)
    assert "tables" not in payload["data"]
    assert any("한 쪽씩만" in w for w in payload["warnings"])


# ── 해석은 이벤트 루프를 막지 않는다 ─────────────────────────────────────────────
class _Files:
    """KIND 대신 fixture PDF 를 주는 가짜 — 주소가 달라도 같은 문서를 준다."""

    async def file(self, url, **_):
        import asyncio
        await asyncio.sleep(0)                        # 실제 내려받기처럼 한 번은 양보한다
        return PDF


async def test_pdf_parsing_does_not_block_other_requests(monkeypatch):
    """해석이 루프 위에서 돌면 그동안 서버의 모든 요청이 멈춘다 — 스레드로 넘겼는지 확인한다."""
    import asyncio
    import time as _time
    from open_esg_korea.services import report_text

    real = extract.page_texts

    def slow(data):
        _time.sleep(0.4)
        return real(data)
    monkeypatch.setattr(extract, "page_texts", slow)

    stamps: list[float] = []

    async def heartbeat():
        for _ in range(30):
            stamps.append(_time.perf_counter())
            await asyncio.sleep(0.02)
    await asyncio.gather(heartbeat(), report_text.load_pages("https://kind.krx.co.kr/x.pdf", _Files()))
    # 루프 위에서 해석하면 박동 사이에 0.4초 넘는 틈이 생긴다(예전 코드 실측 0.438초) — 스레드면 수십 ms.
    assert max(b - a for a, b in zip(stamps, stamps[1:])) < 0.2


async def test_pdfium_never_runs_twice_at_once(monkeypatch):
    """PDFium 은 스레드 안전하지 않다 — 여러 문서를 동시에 열어도 pypdfium2 는 한 번에 하나만."""
    import asyncio
    import threading
    import time as _time
    from open_esg_korea.services import report_text

    real = extract.page_texts
    guard = threading.Lock()
    state = {"now": 0, "max": 0}

    def tracked(data):
        with guard:
            state["now"] += 1
            state["max"] = max(state["max"], state["now"])
        try:
            _time.sleep(0.05)
            return real(data)
        finally:
            with guard:
                state["now"] -= 1
    monkeypatch.setattr(extract, "page_texts", tracked)
    await asyncio.gather(*(report_text.load_document(f"https://kind.krx.co.kr/{i}.pdf", _Files())
                           for i in range(4)))
    assert state["max"] == 1
    assert cache_stats()["documents"] == 4
