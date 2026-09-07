"""KRX ESG 포털 클라이언트 — 호출·간격·캐시를 한 곳에서.

⚠️ 비공식 엔드포인트다. 공표된 한도가 없으므로 **수치가 아니라 예의**로 다룬다:
  - 최소 간격 0.5초(프로세스 시계 하나). 차단은 IP 기준이라 이 머신의 사용자 전원이 같이 막힌다.
  - 등급·보고서는 연 단위로 바뀐다 → 기본 24시간 캐시. 전체 목록(795행)은 하루 한 번만 받는다.
  - 사용자 조회 결과를 저장하지 않는다. 캐시는 메모리에만 두고 프로세스와 함께 사라진다
    (평가기관 저작권 고지 — DB 적재·재배포 금지).
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any

import httpx

from open_esg_korea.krx import codes

USER_AGENT = "open-esg-korea/0.1 (+https://github.com/MarcoYou/open-esg-korea)"
_HEADERS = {
    "User-Agent": USER_AGENT,
    "Referer": f"{codes.BASE_URL}/",
    "X-Requested-With": "XMLHttpRequest",
}

DEFAULT_TTL = 24 * 3600
_MAX_CACHE_ENTRIES = 2000


class KrxClientError(Exception):
    """포털이 JSON 이 아닌 것을 돌려줬거나(차단 페이지·점검) 응답 모양이 기대와 다를 때."""


class KrxEsgClient:
    def __init__(self, http: httpx.AsyncClient | None = None, *,
                 min_interval: float = 0.5, cache_ttl: int = DEFAULT_TTL) -> None:
        self._http = http or httpx.AsyncClient(base_url=codes.BASE_URL, headers=_HEADERS,
                                               timeout=httpx.Timeout(30.0))
        self._min_interval = min_interval
        self._ttl = cache_ttl
        self._lock = asyncio.Lock()
        self._last_call = 0.0
        self._cache: dict[str, tuple[float, dict]] = {}
        self.calls = 0          # 프로세스 누계 — /health 로 노출
        self.cache_hits = 0

    # ── 저수준 ────────────────────────────────────────────────────────────────
    async def _throttled_post(self, path: str, data: dict[str, str]) -> httpx.Response:
        async with self._lock:
            wait = self._min_interval - (time.monotonic() - self._last_call)
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_call = time.monotonic()
            self.calls += 1
        return await self._http.post(path, data=data)

    async def post_json(self, path: str, data: dict[str, Any], *, ttl: int | None = None) -> dict:
        """폼 POST → JSON. 같은 (path, data) 는 TTL 동안 재호출하지 않는다."""
        clean = {k: str(v) for k, v in data.items() if v is not None}
        key = path + "?" + json.dumps(clean, sort_keys=True, ensure_ascii=False)
        now = time.monotonic()
        hit = self._cache.get(key)
        if hit and hit[0] > now:
            self.cache_hits += 1
            return hit[1]
        resp = await self._throttled_post(path, clean)
        resp.raise_for_status()
        try:
            body = resp.json()
        except (json.JSONDecodeError, ValueError) as exc:
            raise KrxClientError(f"KRX ESG 포털이 JSON 이 아닌 응답을 돌려줬습니다 ({path})") from exc
        if not isinstance(body, dict):
            raise KrxClientError(f"응답 모양이 기대와 다릅니다 ({path}): {type(body).__name__}")
        if len(self._cache) >= _MAX_CACHE_ENTRIES:
            oldest = min(self._cache, key=lambda k: self._cache[k][0])
            self._cache.pop(oldest, None)
        self._cache[key] = (now + (self._ttl if ttl is None else ttl), body)
        return body

    async def data(self, code: str, **params: Any) -> dict:
        """공용 데이터 엔드포인트. `code` 가 화면을 고른다."""
        return await self.post_json(codes.DATA_PATH, {"code": code, "bldcode": code, **params})

    # ── 화면별 ────────────────────────────────────────────────────────────────
    async def ratings(self, isu_cd: str, year: int | str | None) -> list[dict]:
        body = await self.data(codes.CODE_RATINGS, isu_cd=isu_cd, sch_yy=year)
        return list(body.get("result") or [])

    async def rating_history(self, isu_cd: str) -> dict:
        return await self.data(codes.CODE_RATING_HISTORY, isu_cd=isu_cd)

    async def report_summary(self, isu_cd: str) -> dict | None:
        rows = (await self.data(codes.CODE_REPORT_SUMMARY, isu_cd=isu_cd)).get("result") or []
        return rows[0] if rows else None

    async def issue_info(self, isu_cd: str) -> dict | None:
        rows = (await self.data(codes.CODE_ISSUE_INFO, isu_cd=isu_cd)).get("result") or []
        return rows[0] if rows else None

    async def report_list(self, isu_cd: str, fr: str, to: str, page: int = 1) -> list[dict]:
        body = await self.data(codes.CODE_REPORT_LIST, isu_cd=isu_cd, fr_work_dt=fr,
                               to_work_dt=to, sch_tp="N", curPage=page)
        return list(body.get("result") or [])

    async def gov_disclosures(self, isu_cd: str, fr: str, to: str, page: int = 1) -> list[dict]:
        body = await self.data(codes.CODE_GOV_DISCLOSURES, isu_cd=isu_cd, fr_work_dt=fr,
                               to_work_dt=to, sch_tp="N", curPage=page)
        return list(body.get("result") or [])

    async def company_list(self, year: int | str, upjong: str = "") -> list[dict]:
        """연도별 전체 상장사 등급표. pageSize=1000 이면 한 번에 다 온다(2025: 795행)."""
        body = await self.data(codes.CODE_COMPANY_LIST, sch_yy=year, upjong=upjong or None,
                               curPage=1, pageSize=1000)
        return list(body.get("result") or [])

    async def gov_indicators(self, isu_cd: str, year: int | str) -> dict | None:
        body = await self.post_json(codes.PATH_GOV_INDICATORS, {"isu_cd": isu_cd, "sch_yy": year})
        rows = body.get("output") or []
        return rows[0] if rows else None

    async def gov_policies(self, isu_cd: str, year: int | str) -> dict | None:
        body = await self.post_json(codes.PATH_GOV_POLICIES, {"isu_cd": isu_cd, "sch_yy": year})
        rows = body.get("output") or []
        return rows[0] if rows else None

    async def finder(self, search_text: str = "") -> list[dict]:
        """회사명 검색기. 빈 검색어면 포털이 아는 전체(유가증권 834사)를 돌려준다 — 그걸 색인으로 쓴다."""
        body = await self.post_json(f"{codes.DATA_PATH}?code={codes.CODE_FINDER}",
                                    {"searchText": search_text, "consonant": ""})
        return list(body.get("block1") or [])

    def stats(self) -> dict:
        return {"calls": self.calls, "cache_hits": self.cache_hits, "cache_entries": len(self._cache)}


_client: KrxEsgClient | None = None


def get_client() -> KrxEsgClient:
    global _client
    if _client is None:
        _client = KrxEsgClient()
    return _client


def set_client(client: KrxEsgClient | None) -> None:
    """테스트·확장이 클라이언트를 갈아 끼울 때."""
    global _client
    _client = client
