"""KIND 원문 뷰어 클라이언트 — 접수번호 하나로 공시 본문 HTML 을 가져온다.

Why: ESG 포털(`krx/client.py`)은 지배구조 **지표**만 준다. 「왜 미준수인가」와 서식 표는 원문 본문에만 있고,
그 본문은 KIND 가 키 없이 준다. OpenDART `document.xml` 과 같은 문서지만 API 키가 필요 없다.

세 번 부른다(`codes.py` 상단 주석 참고). ①뷰어에서 문서번호 → ②경로 응답에서 본문 주소 → ③본문.
①②를 건너뛸 수 없다: 접수번호와 문서번호가 다르고, 본문 주소 끝의 서식번호는 응답에서만 알 수 있다.

예의는 포털과 같다(규칙 1) — 간격 0.5초, 24시간 메모리 캐시, User-Agent 명시. 본문이 5~12MB 라
캐시 항목 수는 작게 잡는다(같은 회사를 연달아 물어보는 것만 아껴도 충분하다).
"""

from __future__ import annotations

import asyncio
import html as htmllib
import re
import time

import httpx

from open_esg_korea.krx import codes

USER_AGENT = "open-esg-korea/0.1 (+https://github.com/MarcoYou/open-esg-korea)"
_HEADERS = {"User-Agent": USER_AGENT, "Referer": f"{codes.KIND_BASE_URL}/"}

DEFAULT_TTL = 24 * 3600
#: 본문 한 건이 5~12MB 다 — 개수로만 막는다(삼성전자 2024 가 11.9MB).
_MAX_CACHE_ENTRIES = 8
#: 12MB 를 받는 데 30초는 모자랐다(실측). 연결은 짧게, 읽기는 넉넉히.
_TIMEOUT = httpx.Timeout(connect=10.0, read=120.0, write=30.0, pool=10.0)
#: 첨부 PDF 상한. 실측 분포는 4MB(삼성)~81MB(NAVER) 다 — 그 위는 받지 않고 주소만 준다.
MAX_FILE_BYTES = 100 * 1024 * 1024

#: <option value='20250530001923|Y'selected="selected">기업지배구조 보고서 공시 (2025.05.30)</option>
#: 첨부서류 쪽은 `|Y` 없이 문서번호만 온다.
_OPTION_RE = re.compile(r"<option\s+value='(\d{10,})(?:\|([YN]))?'[^>]*>(.*?)</option>", re.S)
_SELECT_RE = re.compile(r"<select[^>]*\bid=\"(mainDoc|attachedDoc)\"[^>]*>(.*?)</select>", re.S)
#: parent.setPath('…99667_toc.htm','…99667.htm','/external/…/99667','01','30');
_SETPATH_RE = re.compile(r"parent\.setPath\('([^']*)'\s*,\s*'([^']*)'", re.S)
_TAG_RE = re.compile(r"<[^>]+>")


class KindClientError(Exception):
    """KIND 가 기대한 모양을 돌려주지 않았을 때 — 차단 페이지·점검·화면 개편, 또는 본문 없는 접수번호."""


def _text(fragment: str) -> str:
    return htmllib.unescape(_TAG_RE.sub("", fragment)).replace("\xa0", " ").strip()


def parse_documents(viewer_html: str) -> list[dict[str, str | bool]]:
    """뷰어 HTML → 문서 목록. `kind`=main 이 본문, attached 가 첨부서류.

    `latest=False`(본문 옵션의 `|N`)는 「정정본이 따로 있다」는 뜻이다 — 뷰어가 경고 문구를 띄우는 자리.
    """
    docs: list[dict[str, str | bool]] = []
    for select_id, body in _SELECT_RE.findall(viewer_html):
        for doc_no, latest, label in _OPTION_RE.findall(body):
            docs.append({
                "doc_no": doc_no,
                "kind": "main" if select_id == "mainDoc" else "attached",
                "title": _text(label),
                "latest": latest != "N",
            })
    return docs


def parse_body_url(contents_html: str) -> tuple[str, str]:
    """경로 응답(1KB) → (본문 URL, 목차 URL). 본문은 여기서만 알 수 있다."""
    m = _SETPATH_RE.search(contents_html)
    if not m:
        raise KindClientError("KIND 가 본문 주소를 돌려주지 않았습니다(정정 전 문서이거나 화면이 바뀌었습니다).")
    toc_url, body_url = m.group(1), m.group(2)
    if not body_url:
        raise KindClientError("KIND 본문 주소가 비어 있습니다.")
    return body_url, toc_url


def form_no(body_url: str) -> str:
    """본문 주소 끝의 서식번호(`…/99667.htm` → `99667`). 문서 종류 판정에 쓴다."""
    return body_url.rsplit("/", 1)[-1].split(".")[0]


class KindClient:
    def __init__(self, http: httpx.AsyncClient | None = None, *,
                 min_interval: float = 0.5, cache_ttl: int = DEFAULT_TTL) -> None:
        self._http = http or httpx.AsyncClient(headers=_HEADERS, timeout=_TIMEOUT, follow_redirects=True)
        self._min_interval = min_interval
        self._ttl = cache_ttl
        self._lock = asyncio.Lock()
        self._last_call = 0.0
        self._cache: dict[str, tuple[float, dict]] = {}
        self.calls = 0
        self.cache_hits = 0

    # ── 저수준 ────────────────────────────────────────────────────────────────
    async def _throttled_get(self, url: str) -> httpx.Response:
        async with self._lock:
            wait = self._min_interval - (time.monotonic() - self._last_call)
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_call = time.monotonic()
            self.calls += 1
        return await self._http.get(url)

    async def _get_text(self, url: str) -> str:
        resp = await self._throttled_get(url)
        resp.raise_for_status()
        body = resp.text
        if not body.strip():
            raise KindClientError(f"KIND 가 빈 응답을 돌려줬습니다 ({url}).")
        return body

    def _cached(self, key: str) -> dict | None:
        hit = self._cache.get(key)
        if hit and hit[0] > time.monotonic():
            self.cache_hits += 1
            return hit[1]
        return None

    def _store(self, key: str, value: dict) -> None:
        if len(self._cache) >= _MAX_CACHE_ENTRIES:
            self._cache.pop(min(self._cache, key=lambda k: self._cache[k][0]), None)
        self._cache[key] = (time.monotonic() + self._ttl, value)

    # ── 화면별 ────────────────────────────────────────────────────────────────
    async def documents(self, acpt_no: str) -> list[dict[str, str | bool]]:
        """①뷰어만 — 본문(5~12MB)을 받지 않고 문서 목록만 본다. 「어떤 서식인가」는 이것으로도 알 수 있다."""
        html = await self._get_text(f"{codes.KIND_BASE_URL}{codes.KIND_VIEWER_PATH}"
                                    f"?method=search&acptno={acpt_no}")
        docs = parse_documents(html)
        if not docs:
            raise KindClientError(f"KIND 에 접수번호 {acpt_no} 의 문서가 없습니다(번호가 틀렸거나 원문이 비공개입니다).")
        return docs

    async def document(self, acpt_no: str, doc_no: str | None = None) -> dict:
        """①②③ 전부 — 본문 HTML 까지.

        `doc_no` 를 주면 그 문서를(첨부서류 포함), 없으면 본문 선택의 첫 문서를 연다.
        돌려주는 것: `html`(본문), `docs`(문서 목록), `body_url`·`form_no`(문서 종류 판정용).
        """
        key = f"{acpt_no}/{doc_no or ''}"
        hit = self._cached(key)
        if hit is not None:
            return hit

        docs = await self.documents(acpt_no)
        if doc_no is None:
            main = next((d for d in docs if d["kind"] == "main"), None)
            if main is None:
                raise KindClientError(f"접수번호 {acpt_no} 에 본문 문서가 없습니다(첨부서류만 있습니다).")
            doc = main
        else:
            doc = next((d for d in docs if d["doc_no"] == doc_no),
                       {"doc_no": doc_no, "kind": "main", "title": "", "latest": True})

        contents = await self._get_text(f"{codes.KIND_BASE_URL}{codes.KIND_VIEWER_PATH}"
                                        f"?method=searchContents&docNo={doc['doc_no']}")
        body_url, toc_url = parse_body_url(contents)
        html = await self._get_text(body_url)

        result = {
            "acpt_no": acpt_no,
            "doc_no": doc["doc_no"],
            "title": doc["title"],
            "latest": doc["latest"],
            "form_no": form_no(body_url),
            "body_url": body_url,
            "toc_url": toc_url,
            "viewer_url": codes.KIND_VIEWER_URL.format(acpt_no=acpt_no),
            "docs": docs,
            "html": html,
        }
        self._store(key, result)
        return result

    async def file(self, url: str, *, max_bytes: int = MAX_FILE_BYTES) -> bytes:
        """첨부 파일(보고서 PDF) 원본. **캐시하지 않는다** — 4~80MB 라 메모리에 들고 있을 것이 못 된다.

        부르는 쪽이 텍스트만 뽑아 남기고 바이트는 버린다. 크기는 받기 전에 헤더로 막는다.
        """
        head = await self._throttled_get_head(url)
        size = int(head.headers.get("content-length") or 0)
        if size > max_bytes:
            raise KindClientError(f"첨부 파일이 너무 큽니다({size / 1e6:.0f}MB, 상한 {max_bytes / 1e6:.0f}MB). "
                                  f"원문 주소로 직접 받으세요: {url}")
        resp = await self._throttled_get(url)
        resp.raise_for_status()
        if len(resp.content) > max_bytes:
            raise KindClientError(f"첨부 파일이 너무 큽니다({len(resp.content) / 1e6:.0f}MB).")
        return resp.content

    async def _throttled_get_head(self, url: str) -> httpx.Response:
        """KIND 는 HEAD 에 405 를 준다 — 1바이트 Range 로 크기만 물어본다."""
        async with self._lock:
            wait = self._min_interval - (time.monotonic() - self._last_call)
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_call = time.monotonic()
            self.calls += 1
        resp = await self._http.get(url, headers={"Range": "bytes=0-0"})
        if "content-range" in resp.headers:
            total = resp.headers["content-range"].rsplit("/", 1)[-1]
            resp.headers = httpx.Headers({**resp.headers, "content-length": total})
        return resp

    def stats(self) -> dict:
        return {"calls": self.calls, "cache_hits": self.cache_hits, "cache_entries": len(self._cache)}


_client: KindClient | None = None


def get_kind_client() -> KindClient:
    global _client
    if _client is None:
        _client = KindClient()
    return _client


def set_kind_client(client: KindClient | None) -> None:
    """테스트·확장이 클라이언트를 갈아 끼울 때."""
    global _client
    _client = client
