"""지속가능경영보고서 · 지배구조보고서 공시 목록."""

from __future__ import annotations

import re
from typing import Any

import httpx

from open_esg_korea.krx import codes
from open_esg_korea.krx.client import KrxEsgClient, get_client
from open_esg_korea.krx.kind import KindClient, KindClientError, get_kind_client
from open_esg_korea.services.company import company_block, resolve_company
from open_esg_korea.services.contracts import AnalysisStatus, ToolEnvelope, clean, source_block
from open_esg_korea.services.sustainability_notice import parse_attachments, parse_notice

_STANDARD_RE = re.compile(r'stan-icon\s+([a-z_]+)')
_STANDARD_LABEL = {"gri": "GRI", "sasb": "SASB", "tcfd": "TCFD", "un_sdgs": "UN SDGs"}

#: 접수번호는 **KIND(거래소) 번호**다 — DART 접수번호와 체계가 다르다.
#: 같은 번호를 DART 뷰어(`rcpNo=`)에 넣으면 **다른 회사의 다른 공시**가 열린다
#: (실측 2026-09-07: 삼성전자 `20250530001005` → 에이치솔루션 대규모기업집단현황공시). 그래서 DART 링크는 싣지 않는다.
KIND_URL = codes.KIND_VIEWER_URL


def links(acpt_no: str | None) -> dict[str, str]:
    if not acpt_no:
        return {}
    return {"kind": KIND_URL.format(acpt_no=acpt_no)}


def parse_standards(html: str | None) -> list[str]:
    return [_STANDARD_LABEL.get(k, k) for k in _STANDARD_RE.findall(html or "")]


def parse_report_row(r: dict[str, Any]) -> dict[str, Any]:
    acpt = clean(r.get("acpt_no"))
    return {
        "year": clean(r.get("yy")), "title": clean(r.get("orgn_file_nm")),
        "industry": clean(r.get("upjong")), "standards": parse_standards(r.get("bas_itm_cd_nm")),
        "third_party_verifier": clean(r.get("remk")), "acpt_no": acpt, "links": links(acpt),
    }


def _pick_report(reports: list[dict[str, Any]], year: int | None) -> dict[str, Any] | None:
    """원문 서식을 읽을 한 건. 연도를 주면 그 해, 아니면 최신(목록이 최신순으로 온다)."""
    if year is None:
        return reports[0]
    return next((r for r in reports if r["year"] == str(year)), None)


async def _fetch_notice(report: dict[str, Any], warnings: list[str],
                        kind: KindClient | None) -> dict[str, Any]:
    """자율공시 본문 + 첨부(PDF 주소). **목록을 죽이지 않는다** — KIND 가 막히면 경고만 남기고 넘어간다.

    PDF 본문은 읽지 않는다(4MB 안팎, 표 위주라 텍스트 추출은 따로 검증할 일이다) — 주소만 준다.
    """
    kind = kind or get_kind_client()
    detail: dict[str, Any] = {"year": report["year"], "acpt_no": report["acpt_no"]}
    try:
        doc = await kind.document(report["acpt_no"])
        detail.update(parse_notice(doc["html"]))
        detail["form_no"] = doc["form_no"]
        attachments: list[dict[str, str]] = []
        for other in doc["docs"]:
            if other["kind"] != "attached":
                continue
            att = await kind.document(report["acpt_no"], doc_no=str(other["doc_no"]))
            attachments.extend(parse_attachments(att["html"], att["body_url"]))
        detail["attachments"] = attachments
        if not attachments:
            warnings.append("공시에 첨부된 보고서 파일이 없습니다 — 회사 사이트에만 올렸을 수 있습니다.")
    except (KindClientError, httpx.HTTPError, TimeoutError) as exc:
        warnings.append(f"공시 원문(KIND)을 읽지 못해 목록만 보여줍니다: {exc}")
        detail["unread"] = True
    return detail


async def build_sustainability_reports_payload(company: str, *, from_year: int | None = None,
                                               to_year: int | None = None, year: int | None = None,
                                               client: KrxEsgClient | None = None,
                                               kind: KindClient | None = None) -> dict[str, Any]:
    client = client or get_client()
    res = await resolve_company(company, client)
    env = ToolEnvelope(tool="sustainability_reports", status=res.status, subject=company,
                       warnings=list(res.warnings), source=source_block("reports"))
    if res.status is not AnalysisStatus.EXACT:
        env.data = {"query": company, "candidates": res.candidates}
        return env.to_dict()
    isu = res.selected["isu_cd"]
    fr = f"{from_year or 2015}0101"
    to = f"{to_year or 2099}1231"
    rows = await client.report_list(isu, fr, to)
    reports = [parse_report_row(r) for r in rows]
    summary = await client.report_summary(isu) or {}
    env.status = AnalysisStatus.EXACT if reports else AnalysisStatus.NO_DATA
    if not reports:
        env.warnings.append("포털에 등록된 지속가능경영보고서가 없습니다 — 회사가 보고서를 내지 않았다는 뜻은 아닙니다(자율공시).")
    env.data = {
        "company": company_block(res),
        "summary": {
            "report_count": clean(summary.get("count")),
            "standards_ever_used": [lab for key, lab in _STANDARD_LABEL.items() if clean(summary.get(key)) == "1"],
            "latest_verifier": clean(summary.get("verify")),
        },
        "reports": reports,
    }
    if reports:
        target = _pick_report(reports, year)
        if target is None:
            env.warnings.append(f"{year}년 보고서가 목록에 없어 원문 서식은 읽지 않았습니다. "
                                f"있는 연도: {', '.join(r['year'] for r in reports if r['year'])}.")
        else:
            env.data["detail"] = await _fetch_notice(target, env.warnings, kind)
    return env.to_dict()


async def build_esg_disclosures_payload(company: str, *, from_date: str = "", to_date: str = "",
                                        client: KrxEsgClient | None = None) -> dict[str, Any]:
    client = client or get_client()
    res = await resolve_company(company, client)
    env = ToolEnvelope(tool="esg_disclosures", status=res.status, subject=company,
                       warnings=list(res.warnings), source=source_block("gov_disclosures"))
    if res.status is not AnalysisStatus.EXACT:
        env.data = {"query": company, "candidates": res.candidates}
        return env.to_dict()
    isu = res.selected["isu_cd"]
    rows = await client.gov_disclosures(isu, from_date or "20190101", to_date or "20991231")
    items = [{"title": clean(r.get("title")), "disclosed_at": clean(r.get("discls_procs_ddtm")),
              "acpt_no": clean(r.get("acpt_no")), "links": links(clean(r.get("acpt_no")))} for r in rows]
    env.status = AnalysisStatus.EXACT if items else AnalysisStatus.NO_DATA
    if not items:
        env.warnings.append("조회 기간에 기업지배구조보고서 공시가 없습니다.")
    env.data = {"company": company_block(res), "window": {"from": from_date or "20190101", "to": to_date or "today"},
                "disclosures": items}
    return env.to_dict()
