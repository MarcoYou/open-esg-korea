"""온실가스 — GIR 명세서(회사별)·ETRS 할당/인증·국가 인벤토리 payload.

Why 세 겹: 「이 회사가 얼마나 배출하나」(명세서) → 「할당 대비 얼마나 썼나」(ETRS) → 「그 업종·국가 전체에서 어느 정도인가」
(업종 합산·국가 인벤토리). 값마다 기준이 달라 한 표에 섞지 않는다 — 명세서·인증은 규제 기준 tCO₂eq, 인벤토리는 kt CO₂-eq.

회사 대조: KRX·DART 이름(「SK하이닉스」)과 GIR 법인명(「에스케이하이닉스 주식회사」)이 다르다. `name_keys` 가 법인격을 떼고
음차를 되돌려 겹치면 같은 회사로 본다. 정확히 겹치는 행이 없으면 이름을 품는 행을 「관련 법인」으로 보여 준다(자회사가 따로
지정되는 일이 흔하다 — 삼성디스플레이·포스코퓨처엠).
"""

from __future__ import annotations

import json
import pathlib
from typing import Any

from open_esg_korea.gir import codes as gcodes
from open_esg_korea.gir.client import GirClient, get_gir_client, to_int
from open_esg_korea.krx.client import KrxEsgClient, get_client
from open_esg_korea.services.company import company_block, name_keys, normalize, resolve_company
from open_esg_korea.services.contracts import AnalysisStatus, ToolEnvelope, source_block
from open_esg_korea.services.esg_ratings import current_year

INVENTORY_PATH = pathlib.Path(__file__).resolve().parents[1] / "data" / "ghg_inventory.json"
HISTORY_YEARS = 5
_PROVIDER = "온실가스종합정보센터(GIR)"


def _source(page: str, **extra: Any) -> dict[str, Any]:
    return source_block(page, provider=_PROVIDER, page_url=gcodes.PAGE_URLS[page], **extra)


# ── 이름 대조 ─────────────────────────────────────────────────────────────────
def match_rows(rows: list[dict[str, Any]], name: str, key: str = "name") -> tuple[list[dict], list[dict]]:
    """(정확히 같은 회사 행, 이름을 품거나 품기는 관련 법인 행). 관련 법인은 정확 행을 뺀 것."""
    keys = name_keys(name)
    exact, related = [], []
    for r in rows:
        rk = name_keys(r.get(key, ""))
        if keys & rk:
            exact.append(r)
        elif any(k and (k in x or x in k) and len(min(k, x, key=len)) >= 2 for k in keys for x in rk):
            related.append(r)
    return exact, related


def latest_year_with(rows_by_year: dict[int, list[dict]], name: str) -> int | None:
    for y in sorted(rows_by_year, reverse=True):
        if match_rows(rows_by_year[y], name)[0]:
            return y
    return None


# ── 회사별 ────────────────────────────────────────────────────────────────────
async def _report_disclosure(company: str, warnings: list[str]) -> dict[str, Any] | None:
    """보고서가 공시한 수치를 **범위와 함께** 가져온다. GIR 조회를 죽이지 않는다 — 실패하면 경고만."""
    from open_esg_korea.services import ghg_disclosure
    from open_esg_korea.services.report_text import load_pages
    from open_esg_korea.services.reports import build_sustainability_reports_payload
    try:
        base = await build_sustainability_reports_payload(company)
        detail = (base.get("data") or {}).get("detail") or {}
        attachments = detail.get("attachments") or []
        if not attachments:
            warnings.append("지속가능경영보고서 첨부가 없어 회사 공시치는 비교하지 못했습니다.")
            return None
        pages = await load_pages(attachments[0]["url"])
        mentions = ghg_disclosure.collect_scope_mentions(pages)
        return {"report": {"year": detail.get("year"), "title": detail.get("report_title"),
                           "pdf": attachments[0]["url"], "page_count": len(pages)},
                "mentions": mentions, "basis_axes": ghg_disclosure.basis_summary(mentions),
                "reading_notes": ghg_disclosure.READING_NOTES}
    except Exception as exc:                      # noqa: BLE001 — 보조 정보다. GIR 답변을 막지 않는다.
        warnings.append(f"회사 공시치(보고서)를 읽지 못해 GIR 값만 보여줍니다: {type(exc).__name__}: {exc}")
        return None


async def build_ghg_emissions_payload(company: str, year: int | None = None, *, history_years: int = HISTORY_YEARS,
                                      report: bool = False,
                                      client: KrxEsgClient | None = None, gir: GirClient | None = None) -> dict[str, Any]:
    client = client or get_client()
    gir = gir or get_gir_client()
    res = await resolve_company(company, client)
    env = ToolEnvelope(tool="ghg_emissions", status=res.status, subject=company, warnings=list(res.warnings),
                       source=_source("statement"), license=gcodes.LICENSE_NOTICE)
    if res.status is not AnalysisStatus.EXACT:
        env.data = {"query": company, "candidates": res.candidates}
        return env.to_dict()

    name = res.selected["name"]
    end = year or current_year()
    years = [y for y in range(end, end - history_years - (0 if year else 2), -1) if y >= gcodes.STATEMENT_FIRST_YEAR]
    # year 를 비우면 올해부터 두 해 더 거슬러 「자료가 있는 최신 해」를 찾는다(명세서는 이듬해 중반에 공개된다).
    rows_by_year = {y: await gir.statement(y) for y in years}
    used = year if year else latest_year_with(rows_by_year, name)
    if used is None:
        used = end
    span = [y for y in years if used - history_years < y <= used]
    if year:
        rows_by_year = {y: rows_by_year[y] for y in span}

    exact, related = match_rows(rows_by_year.get(used, []), name)
    history = []
    for y in sorted(span):
        ex, _ = match_rows(rows_by_year.get(y, []), name)
        history.append({"year": y, "emissions_tco2eq": sum(r["emissions_tco2eq"] or 0 for r in ex) if ex else None,
                        "energy_tj": sum(r["energy_tj"] or 0 for r in ex) if ex else None,
                        "rows": len(ex)})
    for i in range(1, len(history)):
        a, b = history[i - 1]["emissions_tco2eq"], history[i]["emissions_tco2eq"]
        history[i]["yoy_pct"] = round((b - a) / a * 100, 1) if a and b is not None else None

    ets = await _ets_block(gir, name, span)
    ets["links"] = {k: v for k, v in {
        "인증 배출량": gcodes.PAGE_URLS["certified"] if ets["by_year"] else None,
        "사전할당량": gcodes.PAGE_URLS["allocation"] if ets["pre_allocation"] else None,
    }.items() if v}

    if exact:
        env.status = AnalysisStatus.EXACT
    else:
        env.status = AnalysisStatus.NO_DATA
        env.warnings.append(f"{used}년 GIR 명세서에 「{name}」 법인이 없습니다. 배출권거래제·목표관리제 대상(연 1,170개 안팎)이 "
                            "아니면 명세서가 없으며, 이는 배출량이 0 이라는 뜻이 아닙니다. 지속가능경영보고서의 자발적 공시치를 보세요.")
        if related:
            env.warnings.append("이름이 겹치는 법인이 있습니다 — 자회사·사업장이 따로 지정된 경우입니다. 아래 관련 법인을 확인하세요.")
    if any(r["designation"] == "사업장" for r in exact):
        env.warnings.append("지정구분이 「사업장」인 행은 해당 사업장만의 배출량입니다(회사 전체가 아닙니다).")

    env.data = {
        "company": company_block(res), "year": used, "unit": "tCO2eq",
        "statement": [_statement_item(r) for r in exact],
        "related_entities": [_statement_item(r) for r in sorted(related, key=lambda r: -(r["emissions_tco2eq"] or 0))[:10]],
        "history": history, "ets": ets,
        "reading_notes": [
            "명세서 값은 업체가 보고하고 제3자가 검증한 규제 기준 배출량(직접+간접)이다 — 보고서의 Scope 1·2·3 과 다를 수 있다.",
            "지정구분 「업체」는 모든 사업장 합산, 「사업장」은 그 사업장만이다.",
            "ETS 인증 배출량 − 할당량 > 0 이면 배출권을 사거나 이월분을 써야 했던 해다.",
        ],
    }
    if report:
        disclosure = await _report_disclosure(company, env.warnings)
        if disclosure:
            env.data["disclosure"] = disclosure
    env.next_actions = [f"ghg_industry(industry=\"{exact[0]['industry']}\", year={used}) — 같은 업종 안 순위" if exact else
                        f"sustainability_reports(company=\"{name}\") — 자발적 공시 원문",
                        f"ghg_emissions(company=\"{name}\", report=True) — 회사 공시치와 범위 대조" if not report else
                        f"sustainability_report_text(company=\"{name}\", find=\"Scope 3\") — 보고서 원문에서 읽기"]
    return env.to_dict()


def _statement_item(r: dict[str, Any]) -> dict[str, Any]:
    return {"name": r["name"], "year": r["year"], "designation": r["designation"], "industry": r["industry"],
            "authority": r["authority"], "emissions_tco2eq": r["emissions_tco2eq"], "energy_tj": r["energy_tj"],
            "verifier": r["verifier"]}


async def _ets_block(gir: GirClient, name: str, years: list[int]) -> dict[str, Any]:
    """배출권거래제: 계획기간 사전할당량 + 연도별 인증 배출량(ETRS). 인증 CSV 에 할당량 열이 없는 해는 사전할당량으로 채운다."""
    pre: list[dict[str, Any]] = []
    alloc_by_year: dict[int, int] = {}
    for period in sorted({p for y in years for p in [gcodes.plan_period_of(y)] if p} | {max(gcodes.PLAN_PERIODS)}):
        rows = await gir.allocation(period)
        exact, _ = match_rows(rows, name, key="업체명")
        if not exact:
            continue
        per_year = {}
        for y in gcodes.PLAN_PERIODS[period]:
            v = sum(to_int(r.get(f"{y}년")) or 0 for r in exact) or None
            per_year[str(y)] = v
            if v:
                alloc_by_year[y] = v
        pre.append({"period": period, "years": f"{gcodes.PLAN_PERIODS[period][0]}-{gcodes.PLAN_PERIODS[period][-1]}",
                    "paid_allocation": exact[0].get("유상여부"), "allocation_by_year_t": per_year})
    by_year: list[dict[str, Any]] = []
    for y in sorted(years):
        rows = await gir.certified(y)
        exact, _ = match_rows(rows, name, key="업체명")
        if not exact:
            continue
        cert = sum(to_int(r.get("인증 배출량(톤)")) or 0 for r in exact) or None
        alloc = sum(to_int(r.get("배출권 할당량(톤)")) or 0 for r in exact) or alloc_by_year.get(y)
        by_year.append({"year": y, "sector": exact[0].get("부문"), "industry": exact[0].get("업종"),
                        "allocation_t": alloc, "certified_t": cert,
                        "surplus_t": (alloc - cert) if alloc is not None and cert is not None else None})
    return {"in_ets": bool(by_year or pre), "by_year": by_year, "pre_allocation": pre}


# ── 업종별 ────────────────────────────────────────────────────────────────────
async def build_ghg_industry_payload(industry: str = "", year: int | None = None, *, top: int = 20,
                                     gir: GirClient | None = None) -> dict[str, Any]:
    gir = gir or get_gir_client()
    env = ToolEnvelope(tool="ghg_industry", status=AnalysisStatus.EXACT, subject=industry or "전체",
                       source=_source("statement"), license=gcodes.LICENSE_NOTICE)
    end = year or current_year()
    rows: list[dict] = []
    used = end
    for y in ([end] if year else [end, end - 1, end - 2]):
        rows = await gir.statement(y)
        used = y
        if rows:
            break
    if not rows:
        env.status = AnalysisStatus.NO_DATA
        env.warnings.append(f"{end}년 명세서 배출량이 아직 공개되지 않았습니다.")
        env.data = {"year": end, "industry": industry}
        return env.to_dict()
    if year is None and used != end:
        env.warnings.append(f"{end}년 명세서가 아직 없어 {used}년으로 보여줍니다.")

    total = sum(r["emissions_tco2eq"] or 0 for r in rows)
    groups: dict[str, list[dict]] = {}
    for r in rows:
        groups.setdefault(r["industry"], []).append(r)
    ranking = sorted(({"industry": k, "companies": len(v), "emissions_tco2eq": sum(r["emissions_tco2eq"] or 0 for r in v),
                       "energy_tj": sum(r["energy_tj"] or 0 for r in v)} for k, v in groups.items()),
                     key=lambda g: -g["emissions_tco2eq"])
    for g in ranking:
        g["share_pct"] = round(g["emissions_tco2eq"] / total * 100, 2) if total else None

    data: dict[str, Any] = {"year": used, "unit": "tCO2eq", "total_reporting_entities": len(rows),
                            "total_emissions_tco2eq": total}
    q = normalize(industry)
    if q:
        hits = [g for g in ranking if q in normalize(g["industry"])]
        if not hits:
            # 글자 하나 틀린 입력(「철깡」)도 잡히도록 글자가 겹치는 업종을 후보로(절반 이상 겹칠 때) — difflib 는 짧은 질의에 약하다.
            chars = set(q)
            need = max(1, len(chars) // 2)
            scored = sorted(((len(chars & set(normalize(x["industry"]))), x["industry"]) for x in ranking), reverse=True)
            scored = [(sc, nm) for sc, nm in scored if sc >= need]
            env.status = AnalysisStatus.NO_DATA
            env.warnings.append(f"「{industry}」에 해당하는 지정업종이 {used}년 명세서에 없습니다.")
            data["industry_candidates"] = [name for score, name in scored if score > 0][:5]
            env.data = data
            return env.to_dict()
        members = [r for g in hits for r in groups[g["industry"]]]
        members.sort(key=lambda r: -(r["emissions_tco2eq"] or 0))
        sub = sum(r["emissions_tco2eq"] or 0 for r in members)
        data.update({"industry": industry, "matched_industries": [g["industry"] for g in hits],
                     "industry_emissions_tco2eq": sub, "industry_share_pct": round(sub / total * 100, 2) if total else None,
                     "companies": [dict(_statement_item(r), rank=i + 1,
                                        share_in_industry_pct=round((r["emissions_tco2eq"] or 0) / sub * 100, 2) if sub else None)
                                   for i, r in enumerate(members[:top])],
                     "companies_total": len(members)})
        env.next_actions = [f"ghg_emissions(company=\"{members[0]['name']}\") — 1위 법인 상세" if members else ""]
    else:
        data["industries"] = ranking[:top]
        data["industries_total"] = len(ranking)
        env.next_actions = [f"ghg_industry(industry=\"{ranking[0]['industry']}\") — 업종 안 법인 순위"]
    env.data = data
    return env.to_dict()


# ── 국가 인벤토리 ──────────────────────────────────────────────────────────────
def load_inventory(path: pathlib.Path = INVENTORY_PATH) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def build_ghg_inventory_payload(find: str = "", years: int = 5, *, inventory: dict[str, Any] | None = None) -> dict[str, Any]:
    inv = inventory or load_inventory()
    env = ToolEnvelope(tool="ghg_national_inventory", status=AnalysisStatus.EXACT, subject=find or "국가 총량·분야",
                       source=_source("inventory"), license=gcodes.LICENSE_NOTICE)
    if inv is None:
        env.status = AnalysisStatus.ERROR
        env.warnings.append("국가 인벤토리 스냅샷이 없습니다 — scripts/refresh_ghg_inventory.py 로 만드세요.")
        return env.to_dict()
    all_years = inv["meta"]["years"]
    span = all_years[-max(1, years):]
    env.source["snapshot_date"] = inv["meta"].get("fetched_at")

    def pick(s: dict[str, Any]) -> dict[str, Any]:
        vals = {y: s["values"].get(y) for y in span}
        first, last = vals[span[0]], vals[span[-1]]
        return {"category": s["category"], "values_kt": vals,
                "change_pct": round((last - first) / first * 100, 1) if first and last is not None else None}

    series = inv["series"]
    q = normalize(find)
    if q:
        hits = [pick(s) for s in series if q in normalize(s["category"])]
        if not hits:
            env.status = AnalysisStatus.NO_DATA
            env.warnings.append(f"「{find}」를 품은 분야가 인벤토리에 없습니다. 예: 철강, 시멘트, 화학, 반도체(전자산업), 도로수송, 폐기물.")
        env.data = {"unit": inv["meta"]["unit"], "years": span, "find": find, "matches": hits[:30], "matches_total": len(hits)}
    else:
        top = [pick(s) for s in series if s["category"].startswith(("총배출량", "순배출량"))
               or s["category"] in ("에너지", "산업공정 및 제품사용", "농업", "LULUCF", "폐기물")]
        env.data = {"unit": inv["meta"]["unit"], "years": span, "overview": top,
                    "note": "분야 세부(철강·시멘트·도로수송 등)는 find= 로 찾는다. 값은 kt CO2-eq (천 톤)."}
    env.next_actions = ["ghg_industry(year=2024) — 명세서 기준 업종별 법인 배출량"]
    return env.to_dict()
