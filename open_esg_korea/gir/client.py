"""GIR·ETRS 클라이언트 — 호출·간격·캐시를 한 곳에서. KRX 클라이언트와 같은 예의(0.5초 간격, 하루 캐시, UA 명시).

Why HTML: 명세서 화면은 JSON 이 없다. 엑셀(xls)도 있지만 xlrd 의존이 붙는다. `maxPageItems=2000` 으로 한 해를
HTML 한 장에 받아 표만 읽는 쪽이 의존성 없이 같은 값을 준다(실측 2024: 1,167행, 895KB, 엑셀과 동일).
ETRS 는 `csvYn=Y` 로 CSV(cp949)를 준다.
"""

from __future__ import annotations

import asyncio
import csv
import html as htmllib
import io
import re
import time
from typing import Any

import httpx

from open_esg_korea.gir import codes

USER_AGENT = "open-esg-korea/0.1 (+https://github.com/MarcoYou/open-esg-korea)"
DEFAULT_TTL = 24 * 3600
_MAX_CACHE_ENTRIES = 200

_TABLE_RE = re.compile(r"<table[^>]*>.*?</table>", re.S)
_TR_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S)
_TD_RE = re.compile(r"<td[^>]*>(.*?)</td>", re.S)
_TAG_RE = re.compile(r"<[^>]+>")


class GirClientError(Exception):
    """GIR/ETRS 가 기대한 표·CSV 를 돌려주지 않았을 때(점검 페이지·차단·화면 개편)."""


def _text(cell: str) -> str:
    return htmllib.unescape(_TAG_RE.sub("", cell)).replace("\xa0", " ").strip()


def to_int(value: Any) -> int | None:
    """'13,594,735' → 13594735. 빈 값·'-'·비수치는 None(미공개/미보고 — 0 이 아니다)."""
    s = str(value or "").replace(",", "").strip()
    if not s or s in ("-", "－"):
        return None
    try:
        return int(float(s))
    except ValueError:
        return None


def parse_statement_html(body: str) -> list[dict[str, Any]]:
    """명세서 배출량 표 → 행 dict. 표는 '법인명' 헤더를 가진 것 하나."""
    table = next((t for t in _TABLE_RE.findall(body) if "법인명" in t), None)
    if table is None:
        raise GirClientError("GIR 명세서 화면에서 표를 찾지 못했습니다(점검 중이거나 화면이 바뀌었습니다).")
    rows: list[dict[str, Any]] = []
    for tr in _TR_RE.findall(table):
        cells = [_text(c) for c in _TD_RE.findall(tr)]
        if len(cells) < 9 or not cells[0].isdigit():
            continue
        rows.append({
            "authority": cells[1], "name": cells[2], "year": to_int(cells[3]),
            "designation": cells[4], "industry": cells[5],
            "emissions_tco2eq": to_int(cells[6]), "energy_tj": to_int(cells[7]),
            "verifier": cells[8], "note": cells[9] if len(cells) > 9 else "",
        })
    return rows


def parse_csv(content: bytes) -> list[dict[str, str]]:
    """ETRS CSV(cp949, 첫 줄 헤더) → dict 행. 헤더의 따옴표·공백은 정리한다."""
    try:
        text = content.decode("cp949")
    except UnicodeDecodeError:
        text = content.decode("utf-8", errors="replace")
    if text.lstrip().startswith("<"):
        raise GirClientError("ETRS 가 CSV 대신 HTML 을 돌려줬습니다(점검 중이거나 파라미터가 바뀌었습니다).")
    reader = csv.reader(io.StringIO(text))
    header = [h.strip().strip('"') for h in next(reader, [])]
    if "업체명" not in header:
        raise GirClientError(f"ETRS CSV 헤더가 기대와 다릅니다: {header[:6]}")
    return [dict(zip(header, [c.strip() for c in r])) for r in reader if r and any(r)]


class GirClient:
    def __init__(self, http: httpx.AsyncClient | None = None, *,
                 min_interval: float = 0.5, cache_ttl: int = DEFAULT_TTL) -> None:
        self._http = http or httpx.AsyncClient(headers={"User-Agent": USER_AGENT}, timeout=httpx.Timeout(60.0),
                                               follow_redirects=True)
        self._min_interval = min_interval
        self._ttl = cache_ttl
        self._lock = asyncio.Lock()
        self._last_call = 0.0
        self._cache: dict[str, tuple[float, Any]] = {}
        self.calls = 0
        self.cache_hits = 0

    async def _get(self, url: str, params: dict[str, Any]) -> bytes:
        async with self._lock:
            wait = self._min_interval - (time.monotonic() - self._last_call)
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_call = time.monotonic()
            self.calls += 1
        resp = await self._http.get(url, params=params)
        resp.raise_for_status()
        return resp.content

    async def _cached(self, key: str, fetch):
        now = time.monotonic()
        hit = self._cache.get(key)
        if hit and hit[0] > now:
            self.cache_hits += 1
            return hit[1]
        value = await fetch()
        if len(self._cache) >= _MAX_CACHE_ENTRIES:
            self._cache.pop(min(self._cache, key=lambda k: self._cache[k][0]), None)
        self._cache[key] = (now + self._ttl, value)
        return value

    # ── 화면별 ────────────────────────────────────────────────────────────────
    async def statement(self, year: int) -> list[dict[str, Any]]:
        """한 해의 명세서 배출량 전체(법인별). 없는 해는 빈 목록."""
        async def fetch():
            body = await self._get(codes.GIR_BASE_URL + codes.STATEMENT_PATH, {
                "menuId": codes.STATEMENT_MENU, "condition.year": year,
                "maxPageItems": codes.STATEMENT_PAGE_SIZE, "pagerOffset": 0})
            return parse_statement_html(body.decode("utf-8", errors="replace"))
        return await self._cached(f"statement:{year}", fetch)

    async def certified(self, year: int) -> list[dict[str, str]]:
        """배출권거래제 이행연도별 할당량·인증 배출량(업체별). 계획기간은 연도에서 정한다."""
        period = codes.plan_period_of(year)
        if period is None:
            return []
        async def fetch():
            body = await self._get(codes.ETRS_BASE_URL + codes.CERTIFIED_PATH, {
                "menuId": "20", "condition.plPeriDgr": period, "condition.infoOpenYn": "Y",
                "condition.infoOpenFnlYn": "Y", "condition.pfYy": year, "csvYn": "Y"})
            return parse_csv(body)
        return await self._cached(f"certified:{year}", fetch)

    async def allocation(self, period: int) -> list[dict[str, str]]:
        """계획기간 사전할당량(업체별, 연도 열)."""
        years = codes.PLAN_PERIODS.get(period)
        if not years:
            return []
        async def fetch():
            body = await self._get(codes.ETRS_BASE_URL + codes.ALLOCATION_PATH, {
                "menuId": "24", "condition.plPeriDgr": period, "condition.pfYy": years[0], "csvYn": "Y"})
            return parse_csv(body)
        return await self._cached(f"allocation:{period}", fetch)

    def stats(self) -> dict[str, Any]:
        return {"calls": self.calls, "cache_hits": self.cache_hits, "cache_entries": len(self._cache)}


_client: GirClient | None = None


def get_gir_client() -> GirClient:
    global _client
    if _client is None:
        _client = GirClient()
    return _client


def set_gir_client(client: GirClient | None) -> None:
    global _client
    _client = client
