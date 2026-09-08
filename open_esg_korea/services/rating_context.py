"""「이 등급이 좋은 편인가」에 답하기 위한 **같은 기관 안의 분포** — 순위나 점수로 바꾸지 않는다.

왜 백분위가 아닌가(2026-09-08 실측, 2025년 795사):

| 기관 | 평가 | 최다 등급 동점 |
|---|---|---|
| 한국ESG연구소 | 198사 | A 에 **120사(61%)** |
| 서스틴베스트 | 198사 | BB 에 72사(36%) |
| KCGS | 782사 | D 에 225사(29%) |
| MSCI | **74사** | A 에 20사(27%) |

등급은 6~7단계뿐이라 동점이 30~60%다. 한국ESG연구소 A 등급은 「상위 6%」일 수도 「상위 67%」일 수도 있다
— 「상위 12%」라고 답하면 **지어낸 정밀도**다. 그래서 백분위를 만들지 않고 **세어서 그대로 보여준다**:
「A 등급 · 평가 198사 중 A 이상 131사(66%) · A 동점 120사」.

모집단도 밝힌다. MSCI 는 795사 중 74사만 평가한다(대형주 위주) — 「MSCI 기준 상위권」은
「전체 상장사 중」이 아니라 「MSCI 가 고른 74사 중」이다. 분모를 감추면 오해를 부른다.
"""

from __future__ import annotations

from typing import Any

from open_esg_korea.krx import codes
from open_esg_korea.services import gics
from open_esg_korea.services.contracts import clean


def _values(rows: list[dict[str, Any]], agency_id: str) -> list[str]:
    """전체 목록에서 그 기관 열만. `-`·빈 값은 **미평가**라 세지 않는다(나쁜 등급이 아니다)."""
    prefix = codes.LIST_AGENCY_PREFIX.get(agency_id)
    if not prefix:
        return []
    return [v for v in (clean(r.get(f"{prefix}_esg")) for r in rows) if v is not None]


def _grade_context(values: list[str], grade: str, agency_id: str) -> dict[str, Any] | None:
    order = codes.GRADE_ORDER.get(agency_id)
    if not order or grade not in order:
        return None
    rank = order.index(grade)
    counts = {g: values.count(g) for g in reversed(order) if values.count(g)}
    at_or_above = sum(n for g, n in counts.items() if g in order and order.index(g) >= rank)
    return {"kind": "grade", "grade": grade, "rated": len(values),
            "at_or_above": at_or_above,
            "at_or_above_pct": round(at_or_above / len(values) * 100, 1) if values else None,
            "same_grade": values.count(grade), "counts": counts}


def _score_context(values: list[str], score: int) -> dict[str, Any]:
    """S&P 는 등급이 아니라 0-100 점수다 — 같은 방식으로 세되 동점은 드물다."""
    numbers = [int(v) for v in values if v.isdigit()]
    at_or_above = sum(1 for n in numbers if n >= score)
    return {"kind": "score", "score": score, "rated": len(numbers),
            "at_or_above": at_or_above,
            "at_or_above_pct": round(at_or_above / len(numbers) * 100, 1) if numbers else None,
            "same_grade": sum(1 for n in numbers if n == score), "counts": {}}


def _peers(rows: list[dict[str, Any]], isu_cd: str) -> tuple[list[dict[str, Any]], dict[str, str] | None]:
    """같은 GICS 산업군의 회사들. 전체 795사보다 이쪽이 「좋은 편인가」에 훨씬 맞는 비교군이다."""
    mine = gics.classify(isu_cd)
    if not mine:
        return [], None
    codes_in_group = {r["isu_cd"] for r in gics.members(group_code=mine["group_code"])}
    return [r for r in rows if clean(r.get("isu_cd")) in codes_in_group], mine


def build_context(rows: list[dict[str, Any]], ratings: list[dict[str, Any]], *,
                  universe: int | None = None, isu_cd: str = "") -> dict[str, Any]:
    """[기관별] 이 회사 등급이 그 기관 평가 대상 안에서 어디쯤인가 — **세어서** 보여준다.

    `isu_cd` 를 주면 **같은 GICS 산업군 안에서도** 함께 센다(비교군이 더 적절하다).
    산업군은 표본이 작아 동점 문제가 더 크므로, 평가 대상이 5사 미만이면 싣지 않는다.
    """
    peer_rows, group = _peers(rows, isu_cd) if isu_cd else ([], None)
    by_agency: dict[str, Any] = {}
    for item in ratings:
        if not item["coverage"]:
            continue
        agency_id = item["agency_id"]
        values = _values(rows, agency_id)
        if not values:
            continue
        value = item["esg"]
        ctx = _score_context(values, value) if isinstance(value, int) else _grade_context(values, str(value), agency_id)
        if ctx:
            ctx["agency"] = item["agency"]
            ctx["coverage_pct"] = round(len(values) / universe * 100, 1) if universe else None
            if peer_rows:
                peer_values = _values(peer_rows, agency_id)
                peer = (_score_context(peer_values, value) if isinstance(value, int)
                        else _grade_context(peer_values, str(value), agency_id))
                if peer and peer["rated"] >= MIN_PEERS:
                    ctx["peer_group"] = peer
            by_agency[agency_id] = ctx
    out: dict[str, Any] = {"universe": universe or len(rows), "by_agency": by_agency}
    if group:
        out["gics_group"] = {"group_code": group["group_code"], "group": group["group"],
                             "sector": group["sector"], "listed": len(gics.members(group_code=group["group_code"]))}
    return out


#: 산업군 표본이 이보다 작으면 분포를 싣지 않는다 — 3~4사에서 「이 등급 이상 2사」는 오해만 부른다.
MIN_PEERS = 5

#: 응답에 늘 싣는다. 「상위 N%」를 만들지 않은 이유를 읽는 쪽이 알아야 한다.
READING_NOTES = [
    "분포는 **같은 기관 안에서만** 센 것이다 — 기관 간 등급을 견주는 데 쓰지 말라.",
    "「상위 N%」를 만들지 않는다. 등급이 6~7단계뿐이라 동점이 30~60%여서 백분위는 지어낸 정밀도가 된다 "
    "— 동점 수를 함께 주니 그것을 보고 판단하라.",
    "분모는 **그 기관이 평가한 회사 수**다. 미평가(`-`)는 세지 않는다 — 나쁜 등급이 아니라 평가 대상이 아닌 것이다.",
    "기관마다 평가 대상이 다르다(2025년 실측: KCGS 782사 · 서스틴베스트·한국ESG연구소 198사 · MSCI 74사) "
    "— 커버리지가 낮은 기관은 대형주 위주라 분포가 편향돼 있다.",
    "산업군(GICS) 안의 분포가 함께 있으면 그쪽이 더 맞는 비교군이다 — 다만 표본이 작아 동점 영향이 더 크다.",
]
