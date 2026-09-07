"""governance_report 페이로드 — 접수번호 고르기 → KIND 원문 → 파서 → scope/find 로 추리기.

포털 지표(`governance_indicators`)가 「무엇이 미준수인가」라면, 이 도구는 「왜 그런가」다. 원문에만 있는 것 셋:
세부원칙 28개에 대한 회사 답변, 서식 표, 미준수 사유(「미진한 부분 및 그 사유」).

연도의 뜻에 주의 — `year` 는 **제출(접수) 연도**다. 2025 년에 낸 보고서의 공시대상 기간은 2024 년이다.
둘 다 응답에 싣는다.
"""

from __future__ import annotations

import re
from typing import Any

from open_esg_korea.krx import codes
from open_esg_korea.krx.client import KrxEsgClient, get_client
from open_esg_korea.krx.kind import KindClient, get_kind_client
from open_esg_korea.services import governance_report as parser
from open_esg_korea.services.company import company_block, resolve_company
from open_esg_korea.services.contracts import AnalysisStatus, ToolEnvelope, clean, source_block

SCOPES = ("principles", "tables", "notes")
_NUMBER_RE = re.compile(r"^\d+-\d+(-\d+)?$")
#: 「[첨부정정]」·「[첨부추가]」는 본문이 없다 — 원본을 고른다(OPM 이 DART 목록에서 겪은 것과 같다).
_SKIP_TITLE_MARKS = ("[첨부정정]", "[첨부추가]")


def _pick(rows: list[dict], year: int | None) -> tuple[dict | None, list[str]]:
    """제출 이력에서 읽을 한 건을 고른다. 최신순으로 온다(rn=1 이 최신)."""
    warnings: list[str] = []
    usable = [r for r in rows if not any(m in (r.get("title") or "") for m in _SKIP_TITLE_MARKS)]
    if not usable:
        return None, warnings
    if year is None:
        return usable[0], warnings
    for r in usable:
        if (clean(r.get("acpt_no")) or "")[:4] == str(year):
            return r, warnings
    years = sorted({(clean(r.get("acpt_no")) or "")[:4] for r in usable}, reverse=True)
    warnings.append(f"{year}년 제출본이 없어 가장 최근({years[0]}년) 보고서를 읽었습니다. "
                    f"있는 제출연도: {', '.join(years)}.")
    return usable[0], warnings


def _matches(needle: str, haystacks: list[str]) -> bool:
    return any(needle in (h or "") for h in haystacks)


def filter_principles(principles: list[dict], find: str, tables: list[dict] | None = None) -> list[dict]:
    """`find` 가 「4-4」면 그 원칙만, 「4」면 핵심원칙 4 의 전부, 「승계」면 원칙문·답변·사유·딸린 서식 표에서 찾는다.

    표까지 뒤지는 이유: 회사가 원칙 답변에 안 쓰고 표에만 적는 말이 있다 — 삼성전자 2026 의 「집중투표」는
    주총 의결 표(1-2-2)와 이사 선임 표(4-3)에만 나온다. 답변만 뒤지면 「없음」이 되어 오해를 부른다.
    """
    if not find:
        return principles
    if _NUMBER_RE.match(find):
        return [p for p in principles if p["no"] == find]
    if find.isdigit():
        return [p for p in principles if p["core"] == int(find)]
    cells: dict[str, list[str]] = {}
    for t in tables or []:
        if t["principle"]:
            cells.setdefault(t["principle"], []).append(t["title"])
            cells[t["principle"]].extend(c for row in t["header"] + t["rows"] for c in row)
    return [p for p in principles
            if _matches(find, [p["text"], p["answer"], *p["notes"].values(), *cells.get(p["no"], [])])]


def filter_tables(tables: list[dict], find: str) -> list[dict]:
    if not find:
        return tables
    if _NUMBER_RE.match(find):
        return [t for t in tables if (t["no"] or "").startswith(find)]
    return [t for t in tables
            if _matches(find, [t["title"], *(c for row in t["header"] + t["rows"] for c in row)])]


def collect_notes(principles: list[dict]) -> list[dict]:
    """미준수 사유가 **적힌** 원칙만. 빈 것은 「사유 없음」이지 「미준수 아님」이 아니다."""
    return [{"no": p["no"], "text": p["text"], "deficiency": p["notes"].get("deficiency", ""),
             "plan": p["notes"].get("plan", "")} for p in principles if p["notes"]]


async def build_governance_report_payload(company: str, *, scope: str = "principles", year: int | None = None,
                                          find: str = "", client: KrxEsgClient | None = None,
                                          kind: KindClient | None = None) -> dict[str, Any]:
    client = client or get_client()
    kind = kind or get_kind_client()
    scope = scope if scope in SCOPES else "principles"

    res = await resolve_company(company, client)
    env = ToolEnvelope(tool="governance_report", status=res.status, subject=company,
                       warnings=list(res.warnings), source=source_block("gov_disclosures"),
                       license=codes.KIND_LICENSE_NOTICE)
    if res.status is not AnalysisStatus.EXACT:
        env.data = {"query": company, "candidates": res.candidates}
        return env.to_dict()

    rows = await client.gov_disclosures(res.selected["isu_cd"], "20190101", "20991231")
    row, warns = _pick(rows, year)
    env.warnings.extend(warns)
    if row is None:
        env.status = AnalysisStatus.NO_DATA
        env.warnings.append("기업지배구조보고서 공시가 없습니다 — 의무공시 대상이 아니거나(자산 5천억 미만) "
                            "아직 제출 전일 수 있습니다. 미제출이지 미준수가 아닙니다.")
        env.data = {"company": company_block(res), "scope": scope}
        return env.to_dict()

    acpt_no = clean(row.get("acpt_no")) or ""
    filing = {"acpt_no": acpt_no, "title": clean(row.get("title")),
              "disclosed_at": clean(row.get("discls_procs_ddtm")), "filed_year": int(acpt_no[:4]) if acpt_no else None,
              "viewer_url": codes.KIND_VIEWER_URL.format(acpt_no=acpt_no)}
    env.source = source_block("gov_disclosures", provider="KRX KIND 공시 원문", page_url=filing["viewer_url"])

    # 금융회사는 「지배구조 연차보고서」로 갈음한다 — 본문에 세부원칙이 없다. 원문(5~12MB)을 받기 전에 제목으로 걸러낸다.
    if codes.KIND_ANNUAL_REPORT_MARK in (filing["title"] or ""):
        env.status = AnalysisStatus.NO_DATA
        env.warnings.append("금융회사는 「금융회사 지배구조 연차보고서」로 갈음합니다 — 서식이 달라 세부원칙 답변·"
                            "서식 표가 없습니다. 내용은 공시에 첨부된 PDF 에 있습니다(위 원문 링크에서 첨부서류 선택).")
        env.data = {"company": company_block(res), "scope": scope, "filing": filing, "form": "annual_report"}
        env.next_actions = [f'esg_disclosures(company="{res.selected["name"]}") — 제출 이력·첨부 확인']
        return env.to_dict()

    doc = await kind.document(acpt_no)
    report = parser.parse_report(doc["html"], form=doc["form_no"])
    filing["form_no"] = doc["form_no"]
    if not doc["latest"]:
        env.warnings.append("이 문서 뒤에 정정본이 있습니다 — 최신본이 아닐 수 있습니다.")

    data: dict[str, Any] = {
        "company": company_block(res), "scope": scope, "find": find, "filing": filing,
        "form": report["kind"], "period": {"start": report["period_start"], "end": report["period_end"]},
        "compliance_rate": report["compliance_rate"],
        "counts": {"principles": len(report["principles"]), "tables": len(report["tables"]),
                   "notes": len(collect_notes(report["principles"]))},
    }

    if report["kind"] != "gov_report":
        env.status = AnalysisStatus.NO_DATA
        env.warnings.append("원문에서 세부원칙을 읽지 못했습니다 — **0개 준수가 아니라 읽지 못한 것**입니다. "
                            "서식이 다르거나(연차보고서) 원문 화면이 바뀌었을 수 있습니다. 원문 링크로 직접 확인하세요.")
        env.data = data
        return env.to_dict()

    if scope == "tables":
        data["tables"] = filter_tables(report["tables"], find)
    elif scope == "notes":
        notes = collect_notes(report["principles"])
        if not find:
            data["notes"] = notes
        elif _NUMBER_RE.match(find):
            data["notes"] = [n for n in notes if n["no"] == find]
        elif find.isdigit():
            data["notes"] = [n for n in notes if n["no"].startswith(find + "-")]
        else:
            data["notes"] = [n for n in notes if _matches(find, [n["text"], n["deficiency"], n["plan"]])]
        data["indicators_not_complied"] = [i["label"] for i in report["indicators"] if i["current"] == "X"]
    else:
        data["principles"] = filter_principles(report["principles"], find, report["tables"])

    if find and not (data.get("principles") or data.get("tables") or data.get("notes")):
        env.warnings.append(f"「{find}」에 걸리는 항목이 없습니다. find 를 비우면 전체를 봅니다.")

    env.data = data
    env.next_actions = [
        f'governance_indicators(company="{res.selected["name"]}") — 핵심지표 15개 O/X 와 준수율',
        f'governance_report(company="{res.selected["name"]}", scope="notes") — 미준수 사유만',
    ]
    return env.to_dict()
