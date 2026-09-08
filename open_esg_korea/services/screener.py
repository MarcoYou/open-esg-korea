"""전체시장 ESG 스크리너 — 연도별 전체 상장사 등급표(한 번에 795행)를 받아 로컬에서 거른다.

캐시는 메모리에만 있고 하루 뒤 사라진다. 등급을 우리 저장소에 적재하지 않는다(라이선스).
"""

from __future__ import annotations

from typing import Any

from open_esg_korea.krx import codes
from open_esg_korea.krx.client import KrxEsgClient, get_client
from open_esg_korea.services import gics
from open_esg_korea.services.contracts import AnalysisStatus, ToolEnvelope, clean, source_block
from open_esg_korea.services.esg_ratings import current_year


def parse_list_row(r: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {"isu_cd": clean(r.get("isu_cd")), "name": clean(r.get("com_abbrv")),
                           "ratings": {}, "has_sustainability_report": clean(r.get("rpt_yn1")) == "Y",
                           "has_governance_report": clean(r.get("rpt_yn2")) == "Y"}
    for agency, pfx in codes.LIST_AGENCY_PREFIX.items():
        esg = clean(r.get(f"{pfx}_esg"))
        if agency == "sp" and esg is not None:
            try:
                esg = int(esg)
            except ValueError:
                pass
        entry: dict[str, Any] = {"esg": esg, "year": clean(r.get(f"{pfx}_yy"))}
        if agency == "kcgs":
            entry.update({"e": clean(r.get("kcgs_env")), "s": clean(r.get("kcgs_soc")), "g": clean(r.get("kcgs_gov"))})
        out["ratings"][agency] = entry
    return out


def grade_at_least(agency: str, grade: str | None, minimum: str) -> bool:
    order = codes.GRADE_ORDER.get(agency)
    if not order or grade is None:
        return False
    g, m = grade.upper(), minimum.upper()
    if g not in order or m not in order:
        return False
    return order.index(g) >= order.index(m)


def resolve_upjong(value: str) -> str:
    """코드(3015)든 이름(전기·전자)이든 코드로. 모르면 빈 문자열(필터 없음)."""
    v = (value or "").strip()
    if not v or v == "all":
        return ""
    if v in codes.UPJONG_CODES:
        return v
    for code, name in codes.UPJONG_CODES.items():
        if name.replace("·", "") == v.replace("·", "").replace(" ", ""):
            return code
    return ""


def _gics_breakdown(companies: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """걸러진 회사들이 어느 산업군에 몰려 있나 — 「산업군별로 보기」의 핵심."""
    counts: dict[tuple[str, str, str], int] = {}
    unknown = 0
    for c in companies:
        g = c.get("gics")
        if not g:
            unknown += 1
            continue
        key = (g["sector"], g["group_code"], g["group"])
        counts[key] = counts.get(key, 0) + 1
    out = [{"sector": s, "group_code": gc, "group": gn, "count": n}
           for (s, gc, gn), n in sorted(counts.items(), key=lambda kv: -kv[1])]
    if unknown:
        out.append({"sector": None, "group_code": None, "group": "분류 없음(스냅샷 미수록)", "count": unknown})
    return out


async def build_screener_payload(*, year: int | None = None, min_kcgs: str = "", min_msci: str = "",
                                 min_kesg: str = "", min_sustinvest: str = "", min_sp_score: int | None = None,
                                 industry: str = "", gics_group: str = "",
                                 require_sustainability_report: bool = False,
                                 limit: int = 50, client: KrxEsgClient | None = None) -> dict[str, Any]:
    client = client or get_client()
    used_year = year or current_year()
    env = ToolEnvelope(tool="esg_screener", status=AnalysisStatus.EXACT, subject=f"{used_year}",
                       source=source_block("company_list"))
    upjong = resolve_upjong(industry)
    if industry and not upjong:
        env.warnings.append(f"업종 「{industry}」를 포털 업종 코드에 대응시키지 못해 업종 필터 없이 조회했습니다. "
                            f"가능한 값: {', '.join(codes.UPJONG_CODES.values())}")
    rows = await client.company_list(used_year, upjong)
    if not rows and year is None:
        rows = await client.company_list(used_year - 1, upjong)
        if rows:
            used_year -= 1
            env.subject = str(used_year)
            env.warnings.append(f"{used_year + 1}년 목록이 아직 없어 {used_year}년 목록을 사용했습니다.")
    universe = [parse_list_row(r) for r in rows]
    for c in universe:                                   # 결과에 산업군을 실어 준다(스냅샷, 네트워크 0)
        hit = gics.classify(c["isu_cd"] or "")
        c["gics"] = {"sector": hit["sector"], "group_code": hit["group_code"], "group": hit["group"]} if hit else None

    matched_groups = gics.resolve_group(gics_group) if gics_group else []
    if gics_group and not matched_groups:
        env.warnings.append(f"GICS 산업군 「{gics_group}」을 찾지 못해 산업군 필터 없이 조회했습니다. "
                            f"가능한 값: {', '.join(sorted({g['group'] for g in gics.groups()}))}")
    wanted_groups = {g["group_code"] for g in matched_groups}

    def keep(c: dict[str, Any]) -> bool:
        rt = c["ratings"]
        if min_kcgs and not grade_at_least("kcgs", rt["kcgs"]["esg"], min_kcgs):
            return False
        if min_msci and not grade_at_least("msci", rt["msci"]["esg"], min_msci):
            return False
        if min_kesg and not grade_at_least("kesg", rt["kesg"]["esg"], min_kesg):
            return False
        if min_sustinvest and not grade_at_least("sustinvest", rt["sustinvest"]["esg"], min_sustinvest):
            return False
        if min_sp_score is not None:
            sp = rt["sp"]["esg"]
            if not isinstance(sp, int) or sp < min_sp_score:
                return False
        if require_sustainability_report and not c["has_sustainability_report"]:
            return False
        if wanted_groups and (c["gics"] or {}).get("group_code") not in wanted_groups:
            return False
        return True

    matched = [c for c in universe if keep(c)]
    env.status = AnalysisStatus.EXACT if matched else AnalysisStatus.NO_DATA
    env.data = {
        "year": used_year,
        "filters": {"min_kcgs": min_kcgs or None, "min_msci": min_msci or None, "min_kesg": min_kesg or None,
                    "min_sustinvest": min_sustinvest or None, "min_sp_score": min_sp_score,
                    "industry": codes.UPJONG_CODES.get(upjong) if upjong else None,
                    "gics_group": [g["group"] for g in matched_groups] or None,
                    "require_sustainability_report": require_sustainability_report},
        "universe_count": len(universe), "matched_count": len(matched),
        "companies": matched[:max(1, limit)], "truncated": len(matched) > limit,
        "gics_breakdown": _gics_breakdown(matched),
        "reading_notes": ["목록은 포털이 게시한 유가증권 상장사 범위다(코스닥 없음).",
                          "「이상」 비교는 기관별 서열표 안에서만 한다 — 기관 간 등급은 비교하지 않는다.",
                          codes.GICS_NOTICE],
    }
    return env.to_dict()
