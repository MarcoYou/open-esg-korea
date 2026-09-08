"""지속가능경영보고서 자율공시 서식(KIND 61979) — 파서와 목록에 얹히는 방식.

fixture 는 삼성전자 2025 자율공시(접수 20250627000633) 실호출 스냅샷이다.
"""

from __future__ import annotations

import pathlib

from open_esg_korea.krx.kind import KindClientError
from open_esg_korea.services.reports import build_sustainability_reports_payload
from open_esg_korea.services.sustainability_notice import parse_attachments, parse_notice
from open_esg_korea.tools.sustainability_reports import _render

FIX = pathlib.Path(__file__).parent / "fixtures"
NOTICE = (FIX / "kind_sr_notice_005930_2025.html").read_text(encoding="utf-8")
ATTACH = (FIX / "kind_sr_attach_005930_2025.html").read_text(encoding="utf-8")
ATTACH_URL = "https://kind.krx.co.kr/external/2025/06/27/000633/20250627000755/99998.htm"


def test_notice_fields_come_out_by_name():
    """항목을 번호가 아니라 이름으로 잇는다 — 서식이 항목을 끼워 넣어도 덜 깨진다."""
    d = parse_notice(NOTICE)
    assert d["report_title"] == "삼성전자 지속가능경영보고서 2025"
    assert d["verifier"].replace("\n", " ") == "딜로이트 안진회계법인"
    assert d["verifier_en"] == "Deloitte Anjin LLC"
    assert d["standards_text"].startswith("GRI(Global Reporting Initiative)")
    assert d["confirmed_at"] == "2025-06-27"


def test_company_site_url_is_pulled_out_of_the_submission_field():
    assert parse_notice(NOTICE)["publisher_url"] == "https://www.samsung.com/sec/sustainability/main/"


def test_summary_keeps_line_breaks_so_the_table_of_contents_survives():
    """목차가 줄 단위로 적혀 있다 — 한 줄로 뭉개면 못 읽는다."""
    lines = parse_notice(NOTICE)["summary"].split("\n")
    assert any("2024년 1월 1일부터 12월 31일까지" in ln for ln in lines)   # 보고 대상 기간 — 목록엔 없다
    assert "5. Facts & Figures" in lines                                  # 목차가 줄로 남아 있다
    assert len(lines) > 10


def test_empty_fields_are_absent_not_blank():
    """서식이 「-」로 비워 둔 자리를 값처럼 싣지 않는다."""
    d = parse_notice(NOTICE)
    assert "notes" not in d                                     # 7. 기타 중요사항이 「-」다


def test_attachment_pdf_url_is_absolute_and_space_safe():
    items = parse_attachments(ATTACH, ATTACH_URL)
    assert len(items) == 1
    assert items[0]["name"] == "삼성전자 지속가능경영보고서_2025.pdf"
    assert items[0]["url"].startswith("https://kind.krx.co.kr/external/2025/06/27/000633/20250627000755/")
    assert items[0]["url"].endswith("_2025.pdf") and " " not in items[0]["url"]


async def test_payload_reads_the_latest_filing_by_default(krx_client, kind_client):
    """최신은 **포털 목록의 최신이 아니라 실제 최신**이다 — 포털이 한 해 늦어 2026 은 KIND 에서 온다."""
    payload = await build_sustainability_reports_payload("삼성전자")
    detail = payload["data"]["detail"]
    assert detail["year"] == "2026" and detail["acpt_no"] == "20260626000871"
    assert detail["form_no"] == "61979"
    assert detail["attachments"][0]["name"].endswith(".pdf")


async def test_asking_for_a_year_with_no_filing_keeps_the_list(krx_client, kind_client):
    """원문을 못 고른다고 목록까지 죽이지 않는다."""
    payload = await build_sustainability_reports_payload("삼성전자", year=2018)
    assert payload["status"] == "exact" and len(payload["data"]["reports"]) == 8
    assert "detail" not in payload["data"]
    assert any("2018년 보고서가 목록에 없어" in w for w in payload["warnings"])


async def test_kind_failure_degrades_to_the_list_with_a_warning(krx_client, kind_client, monkeypatch):
    """KIND 가 막혀도(클라우드에서 실제로 겪은 Akamai 403) 목록은 살아 있어야 한다."""
    async def blocked(*args, **kwargs):
        raise KindClientError("KIND 가 요청을 거부했습니다")
    monkeypatch.setattr(kind_client, "document", blocked)
    payload = await build_sustainability_reports_payload("삼성전자")
    assert payload["status"] == "exact" and len(payload["data"]["reports"]) == 8
    assert payload["data"]["detail"]["unread"] is True
    assert any("공시 원문(KIND)을 읽지 못해" in w for w in payload["warnings"])


async def test_markdown_shows_period_site_and_pdf(krx_client, kind_client):
    """연도를 집으면 그 해 원문을 읽는다 — 2025 건은 FY2024 를 다룬다."""
    text = _render(await build_sustainability_reports_payload("삼성전자", year=2025))
    assert "회사 공개처: https://www.samsung.com/sec/sustainability/main/" in text
    assert "첨부 원문: [삼성전자 지속가능경영보고서_2025.pdf]" in text
    assert "2024년 1월 1일부터 12월 31일까지" in text
