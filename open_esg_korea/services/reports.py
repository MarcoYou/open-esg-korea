"""지속가능경영보고서 · 지배구조보고서 공시 목록."""

from __future__ import annotations

import re
from typing import Any

from open_esg_korea.krx import codes
from open_esg_korea.krx.client import KrxEsgClient, get_client
from open_esg_korea.services.company import company_block, resolve_company
from open_esg_korea.services.contracts import AnalysisStatus, ToolEnvelope, clean, source_block

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


async def build_sustainability_reports_payload(company: str, *, from_year: int | None = None,
                                               to_year: int | None = None,
                                               client: KrxEsgClient | None = None) -> dict[str, Any]:
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
