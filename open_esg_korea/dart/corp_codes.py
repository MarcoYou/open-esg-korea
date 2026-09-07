"""DART 고유번호 명부(corpCode.xml) — 코스닥 회사명 검색을 위한 **보조 색인**.

Why: KRX ESG 포털 검색기는 유가증권 834사만 안다. 그런데 코스닥 종목도 6자리 코드만 있으면 등급표는
나온다. 그러니 「회사명 → 종목코드」 한 단계만 다른 데서 빌리면 코스닥도 이름으로 물을 수 있다.
OpenDART 의 corpCode.xml 은 상장·비상장 약 12만 법인의 고유번호·회사명·영문명·종목코드를 zip 하나(~3.6MB)로
준다. 형제 프로젝트 OPM(open-proxy-mcp) 이 같은 파일을 쓴다.

세 겹으로 읽는다 — 어느 겹이든 같은 모양의 행을 돌려준다:
1. **실시간**: `OPENDART_API_KEY`(OPM 과 같은 이름) 또는 `DART_API_KEY` 가 있으면 내려받아 메모리에 7일 캐시.
2. **번들 스냅샷**: `data/listed_companies.json`(상장사 ~3,900행, 월 1회 갱신 워크플로). 키가 없거나 실시간이
   실패하면 이걸 쓴다 — 그래서 서버는 키 없이도 코스닥을 회사명으로 찾는다.
3. 둘 다 없으면 빈 목록(Phase 1 동작).

- 첫 실시간 적재는 수 초~수십 초가 걸리므로 **필요할 때만**(포털 색인에서 못 찾았을 때) 부른다.
  `peek()` 은 기다리지 않는다 — 실시간이 메모리에 있으면 그것, 아니면 번들.
- 등급이 아니라 공개 원장이므로 저작권 문제는 없다. 실시간 결과는 메모리에만 둔다(프로젝트 규칙).
- ⚠️ DART 는 상장폐지돼도 stock_code 를 지우지 않는다(OPM 실측: 신한은행 000010·우리은행 000030).
  그래서 「명부에 있다 = 상장 중」이 아니다. 여기서 찾은 종목은 등급표가 비어 있을 수 있다.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import io
import json
import os
import pathlib
import re
import time
import xml.etree.ElementTree as ET
import zipfile
from typing import Any

import httpx

OPENDART_BASE_URL = "https://opendart.fss.or.kr/api"
CORP_CODE_PATH = "/corpCode.xml"
DEFAULT_TTL = 7 * 24 * 3600
ENV_KEYS = ("OPENDART_API_KEY", "DART_API_KEY")
USER_AGENT = "open-esg-korea/0.1 (+https://github.com/MarcoYou/open-esg-korea)"
FIELDS = ("isu_cd", "name", "eng_name", "corp_code", "modify_date")
BUNDLE_PATH = pathlib.Path(__file__).resolve().parents[1] / "data" / "listed_companies.json"
STALE_AFTER_DAYS = 120          # 번들이 이보다 오래되면 경고 — 갱신 워크플로가 멈췄다는 신호

_STATUS_RE = re.compile(r"<status>(\d+)</status>")
_MESSAGE_RE = re.compile(r"<message>(.*?)</message>", re.S)


class DartClientError(Exception):
    """OpenDART 가 zip 대신 XML 오류(키 오류 010·한도 초과 020/021 등)나 해석 불가 응답을 돌려줬을 때."""

    def __init__(self, status: str, message: str) -> None:
        self.status = status
        super().__init__(f"OpenDART {status}: {message}".strip() if status else message)


def api_key_from_env() -> str:
    for name in ENV_KEYS:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return ""


def parse_listed(content: bytes) -> list[dict[str, str]]:
    """corpCode.xml zip → 종목코드가 있는 법인만. 비상장(stock_code 공백)은 여기서 버린다."""
    if content[:2] != b"PK":
        text = content.decode("utf-8", errors="replace")
        status = _STATUS_RE.search(text)
        message = _MESSAGE_RE.search(text)
        raise DartClientError(status.group(1) if status else "",
                              message.group(1).strip() if message else "corpCode.xml 응답이 zip 이 아닙니다.")
    rows: list[dict[str, str]] = []
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as z:
            name = next((n for n in z.namelist() if n.lower().endswith(".xml")), None)
            if name is None:
                raise DartClientError("", "corpCode zip 안에 XML 이 없습니다.")
            with z.open(name) as fh:
                for _event, el in ET.iterparse(fh):
                    if el.tag != "list":
                        continue
                    stock = (el.findtext("stock_code") or "").strip()
                    if len(stock) == 6 and stock.isdigit():
                        rows.append({
                            "isu_cd": stock,
                            "name": (el.findtext("corp_name") or "").strip(),
                            "eng_name": (el.findtext("corp_eng_name") or "").strip(),
                            "corp_code": (el.findtext("corp_code") or "").strip(),
                            "modify_date": (el.findtext("modify_date") or "").strip(),
                        })
                    el.clear()
    except (zipfile.BadZipFile, ET.ParseError) as exc:
        raise DartClientError("", f"corpCode.xml 을 해석할 수 없습니다: {exc}") from exc
    return rows


def load_bundle(path: pathlib.Path = BUNDLE_PATH) -> dict[str, Any] | None:
    """동봉 스냅샷 → {"meta": {...}, "rows": [행 dict]}. 파일이 없거나 깨졌으면 None(번들 없이 동작)."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        fields = raw["meta"].get("fields", list(FIELDS))
        rows = [dict(zip(fields, r)) for r in raw["rows"]]
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return {"meta": raw["meta"], "rows": rows}


class DartCorpIndex:
    def __init__(self, http: httpx.AsyncClient | None = None, *, api_key: str | None = None,
                 ttl: int = DEFAULT_TTL, bundle_path: pathlib.Path | None = BUNDLE_PATH) -> None:
        self._http = http or httpx.AsyncClient(base_url=OPENDART_BASE_URL, headers={"User-Agent": USER_AGENT},
                                               timeout=httpx.Timeout(180.0))
        self._api_key = api_key_from_env() if api_key is None else api_key
        self._ttl = ttl
        self._lock = asyncio.Lock()
        self._rows: list[dict[str, str]] | None = None
        self._expires = 0.0
        self._bundle_path = bundle_path
        self._bundle: dict[str, Any] | None = None
        self._bundle_loaded = False
        self.downloads = 0
        self.source = "none"            # 마지막으로 행을 돌려준 겹: live | bundle | none
        self.last_error: str = ""

    # ── 상태 ─────────────────────────────────────────────────────────────────
    @property
    def live_enabled(self) -> bool:
        return bool(self._api_key)

    def bundle(self) -> dict[str, Any] | None:
        if not self._bundle_loaded:
            self._bundle_loaded = True
            self._bundle = load_bundle(self._bundle_path) if self._bundle_path else None
        return self._bundle

    @property
    def enabled(self) -> bool:
        """이름으로 찾을 명부가 하나라도 있나(실시간 키 또는 번들)."""
        return self.live_enabled or self.bundle() is not None

    def bundle_date(self) -> str:
        b = self.bundle()
        return (b or {}).get("meta", {}).get("fetched_at", "")

    def bundle_age_days(self) -> int | None:
        try:
            return (dt.date.today() - dt.date.fromisoformat(self.bundle_date())).days
        except ValueError:
            return None

    def _live_rows(self) -> list[dict[str, str]] | None:
        if self._rows is not None and self._expires > time.monotonic():
            return self._rows
        return None

    # ── 읽기 ─────────────────────────────────────────────────────────────────
    def peek(self) -> list[dict[str, str]]:
        """기다리지 않는다 — 실시간이 메모리에 있으면 그것, 아니면 번들, 아니면 빈 목록."""
        live = self._live_rows()
        if live is not None:
            self.source = "live"
            return live
        b = self.bundle()
        if b is not None:
            self.source = "bundle"
            return b["rows"]
        return []

    async def listed(self) -> list[dict[str, str]]:
        """실시간(키 있을 때) → 실패하면 번들. 번들도 없을 때만 예외를 올린다."""
        if self.live_enabled:
            try:
                async with self._lock:
                    live = self._live_rows()
                    if live is None:
                        resp = await self._http.get(CORP_CODE_PATH, params={"crtfc_key": self._api_key})
                        resp.raise_for_status()
                        self._rows = parse_listed(resp.content)
                        self._expires = time.monotonic() + self._ttl
                        self.downloads += 1
                        self.last_error = ""
                    self.source = "live"
                    return self._rows
            except (DartClientError, httpx.HTTPError, asyncio.TimeoutError, TimeoutError) as exc:
                self.last_error = f"{type(exc).__name__}: {exc}"
                if self.bundle() is None:
                    raise
        b = self.bundle()
        if b is not None:
            self.source = "bundle"
            return b["rows"]
        self.source = "none"
        return []

    def stats(self) -> dict[str, Any]:
        live = self._live_rows()
        return {"live_enabled": self.live_enabled, "downloads": self.downloads,
                "live_rows": len(live) if live is not None else 0,
                "bundle_rows": len(self.bundle()["rows"]) if self.bundle() else 0,
                "bundle_date": self.bundle_date(), "source": self.source, "last_error": self.last_error}


_index: DartCorpIndex | None = None


def get_index() -> DartCorpIndex:
    global _index
    if _index is None:
        _index = DartCorpIndex()
    return _index


def set_index(index: DartCorpIndex | None) -> None:
    """테스트·확장이 색인을 갈아 끼울 때."""
    global _index
    _index = index
