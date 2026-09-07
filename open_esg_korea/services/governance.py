"""기업지배구조보고서 기반 핵심지표 15 · 정책 채택 74 — KRX 가 보고서에서 뽑아 둔 O/X."""

from __future__ import annotations

from typing import Any

from open_esg_korea.krx import codes
from open_esg_korea.krx.client import KrxEsgClient, get_client
from open_esg_korea.services.company import company_block, resolve_company
from open_esg_korea.services.contracts import AnalysisStatus, ToolEnvelope, clean, source_block
from open_esg_korea.services.esg_ratings import current_year


def _ox(v: Any) -> bool | None:
    s = clean(v)
    if s is None:
        return None
    return {"O": True, "X": False, "Y": True, "N": False}.get(s.upper(), None)


def parse_indicators(row: dict[str, Any]) -> dict[str, Any]:
    items = []
    for key, (no, label) in codes.GOV_INDICATORS.items():
        items.append({"no": no, "key": key, "label": label, "complied": _ox(row.get(key))})
    known = [i for i in items if i["complied"] is not None]
    return {"compliance_rate": clean(row.get("obr_rt")),
            "complied_count": sum(1 for i in known if i["complied"]),
            "answered_count": len(known), "indicators": items}


def parse_policies(row: dict[str, Any]) -> list[dict[str, Any]]:
    items = []
    for key, (no, label) in codes.GOV_POLICIES.items():
        items.append({"no": no, "key": key, "label": label, "adopted": _ox(row.get(key)),
                      "fact_item": no in codes.GOV_POLICY_FACT_ITEMS})
    return sorted(items, key=lambda i: i["no"])


async def _resolve_year_row(fetch, isu: str, year: int | None, warnings: list[str]) -> tuple[int, dict | None]:
    want = year or current_year()
    row = await fetch(isu, want)
    if row is None and year is None:
        row = await fetch(isu, want - 1)
        if row is not None:
            warnings.append(f"{want}년 보고서가 아직 없어 {want - 1}년 기준으로 보여줍니다.")
            return want - 1, row
    return want, row


async def build_governance_indicators_payload(company: str, year: int | None = None, *,
                                              compare: str = "", client: KrxEsgClient | None = None) -> dict[str, Any]:
    client = client or get_client()
    res = await resolve_company(company, client)
    env = ToolEnvelope(tool="governance_indicators", status=res.status, subject=company,
                       warnings=list(res.warnings), source=source_block("gov_indicators"))
    if res.status is not AnalysisStatus.EXACT:
        env.data = {"query": company, "candidates": res.candidates}
        return env.to_dict()
    isu = res.selected["isu_cd"]
    used_year, row = await _resolve_year_row(client.gov_indicators, isu, year, env.warnings)
    if row is None:
        env.status = AnalysisStatus.NO_DATA
        env.warnings.append(f"{used_year}년 기업지배구조보고서 핵심지표가 포털에 없습니다 — 자산 5천억 미만 등 "
                            "의무공시 대상이 아니거나 아직 제출 전일 수 있습니다.")
        env.data = {"company": company_block(res), "year": used_year}
        return env.to_dict()
    data: dict[str, Any] = {"company": company_block(res), "year": used_year, **parse_indicators(row),
                            "basis": "상장법인이 제출한 기업지배구조보고서(정정 포함) 기준, KRX 집계"}
    if compare:
        cmp_res = await resolve_company(compare, client)
        if cmp_res.status is AnalysisStatus.EXACT:
            crow = await client.gov_indicators(cmp_res.selected["isu_cd"], used_year)
            data["compare"] = {"company": company_block(cmp_res),
                               **(parse_indicators(crow) if crow else {"indicators": [], "compliance_rate": None})}
            if crow is None:
                env.warnings.append(f"비교회사 {cmp_res.selected['name']} 의 {used_year}년 핵심지표가 없습니다.")
        else:
            env.warnings.append(f"비교회사 「{compare}」를 확정하지 못했습니다: " + "; ".join(cmp_res.warnings))
    env.data = data
    env.next_actions = [f"governance_policies(company=\"{res.selected['name']}\", year={used_year}) — 정책 채택 74개 항목"]
    return env.to_dict()


async def build_governance_policies_payload(company: str, year: int | None = None, *,
                                            client: KrxEsgClient | None = None) -> dict[str, Any]:
    client = client or get_client()
    res = await resolve_company(company, client)
    env = ToolEnvelope(tool="governance_policies", status=res.status, subject=company,
                       warnings=list(res.warnings), source=source_block("gov_policies"))
    if res.status is not AnalysisStatus.EXACT:
        env.data = {"query": company, "candidates": res.candidates}
        return env.to_dict()
    isu = res.selected["isu_cd"]
    used_year, row = await _resolve_year_row(client.gov_policies, isu, year, env.warnings)
    if row is None:
        env.status = AnalysisStatus.NO_DATA
        env.warnings.append(f"{used_year}년 기업지배구조보고서 정책 항목이 포털에 없습니다.")
        env.data = {"company": company_block(res), "year": used_year}
        return env.to_dict()
    items = parse_policies(row)
    env.data = {"company": company_block(res), "year": used_year, "policies": items,
                "adopted_count": sum(1 for i in items if i["adopted"] and not i["fact_item"]),
                "reading_notes": ["O/X 개수는 준수율이 아니다. `fact_item` 이 true 인 항목은 사실 여부를 묻는 것이라 "
                                  "(예: 불성실공시법인 지정 여부) O 가 나쁜 쪽일 수 있다. 항목별로 읽어야 한다."]}
    return env.to_dict()
