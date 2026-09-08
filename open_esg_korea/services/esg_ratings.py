"""기관별 ESG 등급 — 등급표(연도) + 3년 KCGS 추이."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from open_esg_korea.krx import codes
from open_esg_korea.krx.client import KrxEsgClient, get_client
from open_esg_korea.services.safety import EXTERNAL_ERRORS
from open_esg_korea.services.company import company_block, resolve_company
from open_esg_korea.services.contracts import AnalysisStatus, ToolEnvelope, clean, source_block
from open_esg_korea.services.rating_context import READING_NOTES as CONTEXT_NOTES, build_context

_KST = timezone(timedelta(hours=9))


def current_year() -> int:
    return datetime.now(_KST).year


def parse_ratings_row(row: dict[str, Any]) -> list[dict[str, Any]]:
    """`inst_nm1`/`esg_grd1`… 슬롯 키를 기관별 dict 로. `-` 는 None + coverage=False."""
    out: list[dict[str, Any]] = []
    for slot, meta in codes.RATING_SLOTS.items():
        esg = clean(row.get(f"esg_grd{slot}"))
        item = {
            "agency": meta["name"], "agency_id": meta["id"], "scale": meta["scale"],
            "year": clean(row.get(f"yy{slot}")),
            "esg": esg,
            "e": clean(row.get(f"envron_grd{slot}")),
            "s": clean(row.get(f"soc_grd{slot}")),
            "g": clean(row.get(f"govnc_grd{slot}")),
            "coverage": esg is not None,
        }
        if meta["kind"] == "score" and esg is not None:
            try:
                item["esg"] = int(esg)
            except ValueError:
                pass
        if clean(row.get(f"attach_yn{slot}")) == "Y":
            item["attachment"] = clean(row.get(f"attach_file_nm{slot}"))
        out.append(item)
    return out


def parse_history(body: dict[str, Any]) -> list[dict[str, Any]]:
    rows = body.get("block1") or []
    out = []
    for r in rows:
        out.append({"year": clean(r.get("yy")), "kcgs_esg": clean(r.get("esg_grd")),
                    "sales_100m_krw": clean(r.get("sales")), "operating_income_100m_krw": clean(r.get("youngup"))})
    return out


async def build_esg_ratings_payload(company: str, year: int | None = None, *,
                                    client: KrxEsgClient | None = None) -> dict[str, Any]:
    client = client or get_client()
    res = await resolve_company(company, client)
    env = ToolEnvelope(tool="esg_ratings", status=res.status, subject=company,
                       warnings=list(res.warnings), source=source_block("ratings"))
    if res.status is not AnalysisStatus.EXACT:
        env.data = {"query": company, "candidates": res.candidates}
        return env.to_dict()

    isu = res.selected["isu_cd"]
    want = year or current_year()
    rows = await client.ratings(isu, want)
    ratings = parse_ratings_row(rows[0]) if rows else []
    used_year = want
    # 연초에는 올해 등급이 아직 없다 — 전년으로 한 번 물러선다(그 사실을 밝힌다).
    if year is None and not any(r["coverage"] for r in ratings):
        used_year = want - 1
        rows = await client.ratings(isu, used_year)
        ratings = parse_ratings_row(rows[0]) if rows else []
        env.warnings.append(f"{want}년 등급이 아직 없어 {used_year}년 등급을 보여줍니다.")

    history = parse_history(await client.rating_history(isu))
    covered = [r for r in ratings if r["coverage"]]
    env.status = AnalysisStatus.EXACT if covered or history else AnalysisStatus.NO_DATA
    if not covered:
        env.warnings.append(f"{used_year}년에 이 회사를 평가한 기관이 포털에 없습니다 — 등급이 나쁘다는 뜻이 아닙니다.")
    env.data = {
        "company": company_block(res), "year": used_year, "ratings": ratings,
        "kcgs_history": history,
        "reading_notes": [
            "기관마다 스케일이 다르다 — 서로 다른 기관의 등급을 같은 줄에 놓고 비교하지 않는다.",
            "S&P 는 등급이 아니라 0-100 점수다.",
            "연도는 평가 발표 연도(포털 표기)다.",
        ],
    }
    if covered:
        # 「이 등급이 좋은 편인가」 — 같은 기관 안에서 세어 준다. 전체 목록은 24시간 캐시라 대개 공짜다.
        try:
            all_rows = await client.company_list(used_year)
        except EXTERNAL_ERRORS as exc:
            env.warnings.append(f"등급 분포를 계산하지 못해 회사 등급만 보여줍니다: {type(exc).__name__}")
        else:
            if all_rows:
                env.data["distribution"] = {**build_context(all_rows, ratings, universe=len(all_rows)),
                                            "year": used_year, "reading_notes": CONTEXT_NOTES}
    env.next_actions = [f"governance_indicators(company=\"{res.selected['name']}\") — 핵심지표 15개 준수 여부",
                        f"sustainability_reports(company=\"{res.selected['name']}\") — 보고서 작성기준·검증기관"]
    return env.to_dict()
