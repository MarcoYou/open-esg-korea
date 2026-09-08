"""GICS 산업분류 — 「종목코드 → 경제섹터·산업군」 동봉 스냅샷.

Why 스냅샷: 분류는 분기 정도에만 바뀌는데, 지수 포털(index.krx.co.kr)은 ESG 포털·KIND 와 **또 다른 호스트**라
OTP 토큰과 쿠키가 필요하다. 조회할 때마다 두드릴 이유가 없다. 갱신은 `scripts/refresh_krx_gics.py` 로만 한다
(상장사 명부·국가 인벤토리 스냅샷과 같은 규율).

**다른 분류와 섞지 않는다.** 이 프로젝트엔 업종 체계가 셋이고 서로 다르다:
  GICS 산업군 25개        — 여기(KRX 가 S&P·MSCI 기준으로 부여)
  포털 업종 21개          — `codes.UPJONG_CODES`, 지속가능경영보고서 목록 필터
  GIR 지정업종            — 온실가스 명세서, 「반도체 제조업」처럼 규제 목적 분류
같은 회사가 셋 다 다른 이름을 받는다(삼성전자: 하드웨어및IT장비 / 전기·전자 / 반도체 제조업).
"""

from __future__ import annotations

import json
import pathlib
from typing import Any

from open_esg_korea.krx import codes

SNAPSHOT_PATH = pathlib.Path(__file__).resolve().parents[1] / "data" / "krx_gics.json"
#: 스냅샷 행의 열 순서. 리스트로 저장해 파일을 작게 유지한다(상장사 명부와 같은 방식).
FIELDS = ["isu_cd", "name", "market", "sector_code", "sector", "group_code", "group"]

_index: dict[str, dict[str, str]] | None = None
_meta: dict[str, Any] = {}


def _load() -> dict[str, dict[str, str]]:
    global _index, _meta
    if _index is None:
        if not SNAPSHOT_PATH.exists():
            _index, _meta = {}, {}
            return _index
        body = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
        _meta = body.get("meta", {})
        _index = {row[0]: dict(zip(FIELDS, row)) for row in body.get("rows", [])}
    return _index


def reload_snapshot() -> None:
    """테스트가 스냅샷을 갈아 끼울 때."""
    global _index, _meta
    _index, _meta = None, {}


def meta() -> dict[str, Any]:
    _load()
    return dict(_meta)


def classify(isu_cd: str) -> dict[str, str] | None:
    """종목코드 → GICS 분류. 없으면 None — **분류가 없다는 뜻이지 상장이 아니라는 뜻이 아니다**
    (스냅샷 기준일 이후 상장했거나, 그 시장을 안 받았을 수 있다)."""
    return _load().get(str(isu_cd).strip())


def members(*, group_code: str = "", sector_code: str = "", market: str = "") -> list[dict[str, str]]:
    """산업군(4자리)·섹터(2자리)·시장으로 고른 종목들. 인자를 다 비우면 전체."""
    rows = _load().values()
    if group_code:
        rows = [r for r in rows if r["group_code"] == group_code]
    if sector_code:
        rows = [r for r in rows if r["sector_code"] == sector_code]
    if market:
        rows = [r for r in rows if r["market"].upper() == market.upper()]
    return sorted(rows, key=lambda r: r["isu_cd"])


def groups(market: str = "") -> list[dict[str, Any]]:
    """산업군 목록 + 종목 수. 「무엇으로 나눌 수 있나」를 보여주는 용도."""
    counts: dict[tuple[str, str, str, str], int] = {}
    for row in _load().values():
        if market and row["market"].upper() != market.upper():
            continue
        key = (row["sector_code"], row["sector"], row["group_code"], row["group"])
        counts[key] = counts.get(key, 0) + 1
    return [{"sector_code": s, "sector": sn, "group_code": g, "group": gn, "count": n}
            for (s, sn, g, gn), n in sorted(counts.items())]


def resolve_group(query: str) -> list[dict[str, str]]:
    """「4520」·「하드웨어」·「정보기술」 → 해당 산업군들. 코드·이름·섹터명 어느 쪽으로도 찾는다."""
    q = (query or "").strip()
    if not q:
        return []
    out = []
    for g in groups():
        if q == g["group_code"] or q == g["sector_code"] or q in g["group"] or q in g["sector"]:
            out.append(g)
    return out


def annotate(isu_cd: str) -> dict[str, Any]:
    """응답에 실을 한 조각. 분류가 없으면 그 사실을 말한다 — 조용히 비우지 않는다."""
    hit = classify(isu_cd)
    if not hit:
        return {"gics": None,
                "note": "GICS 산업분류 스냅샷에 이 종목이 없습니다 — 스냅샷 기준일 이후 상장했거나 "
                        f"수집 대상 시장이 아닐 수 있습니다(기준일 {meta().get('as_of', '?')})."}
    return {"gics": {"sector_code": hit["sector_code"], "sector": hit["sector"],
                     "group_code": hit["group_code"], "group": hit["group"], "market": hit["market"]},
            "note": codes.GICS_NOTICE}
