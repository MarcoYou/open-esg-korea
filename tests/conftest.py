"""네트워크 0 — KRX·DART 응답을 fixture 로 대신하는 httpx.MockTransport.

실제 클라이언트(`KrxEsgClient`·`DartCorpIndex`)를 그대로 쓴다. 가짜는 전송층 하나뿐이라 캐시·간격·파싱 경로가
전부 테스트를 거친다. DART 명부는 XML fixture 를 요청 시점에 zip 으로 싸서 돌려준다(실제 응답 모양).
"""

from __future__ import annotations

import io
import json
import pathlib
import zipfile
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from open_esg_korea.dart.corp_codes import CORP_CODE_PATH, OPENDART_BASE_URL, DartCorpIndex, set_index
from open_esg_korea.krx import codes
from open_esg_korea.krx.client import KrxEsgClient, set_client

FIX = pathlib.Path(__file__).parent / "fixtures"


def _load(name: str) -> dict:
    return json.loads((FIX / name).read_text(encoding="utf-8"))


def corpcode_zip() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("CORPCODE.xml", (FIX / "corpcode_subset.xml").read_bytes())
    return buf.getvalue()


def dart_route(request: httpx.Request) -> httpx.Response:
    url = urlparse(str(request.url))
    qs = {k: v[0] for k, v in parse_qs(url.query).items()}
    if not url.path.endswith(CORP_CODE_PATH):      # base_url 이 /api 를 품는다
        return httpx.Response(404, text="no such api")
    if qs.get("crtfc_key") == "bad":
        return httpx.Response(200, content=b'<?xml version="1.0"?><result><status>010</status>'
                                            b"<message>\xeb\x93\xb1\xeb\xa1\x9d\xeb\x90\x98\xec\xa7\x80 \xec\x95\x8a\xec\x9d\x80 \xed\x82\xa4\xec\x9e\x85\xeb\x8b\x88\xeb\x8b\xa4.</message></result>")
    if qs.get("crtfc_key") == "down":
        return httpx.Response(503, text="maintenance")
    return httpx.Response(200, content=corpcode_zip(), headers={"content-type": "application/x-msdownload"})


def route(request: httpx.Request) -> httpx.Response:
    url = urlparse(str(request.url))
    if url.netloc.endswith("opendart.fss.or.kr"):
        return dart_route(request)
    form = {k: v[0] for k, v in parse_qs(request.content.decode("utf-8")).items()}
    qs = {k: v[0] for k, v in parse_qs(url.query).items()}
    isu = form.get("isu_cd", "")
    year = form.get("sch_yy", "")

    if url.path == codes.PATH_GOV_INDICATORS:
        return httpx.Response(200, json=_load("gov_indicators_005930_2025.json" if (isu, year) == ("005930", "2025")
                                              else "gov_indicators_unknown.json"))
    if url.path == codes.PATH_GOV_POLICIES:
        return httpx.Response(200, json=_load("gov_policies_005930_2025.json") if (isu, year) == ("005930", "2025")
                              else {"output": []})
    if url.path != codes.DATA_PATH:
        return httpx.Response(404, text="no such page")

    if qs.get("code") == codes.CODE_FINDER:
        rows = _load("finder_subset.json")["block1"]
        q = form.get("searchText", "")
        return httpx.Response(200, json={"block1": [r for r in rows if q in r["com_abbrv"]] if q else rows})

    code = form.get("code")
    if code == codes.CODE_RATINGS:
        if isu != "005930":
            return httpx.Response(200, json={"result": [{"isu_cd": isu, "com_abbrv": "x",
                                                         **{f"esg_grd{s}": "-" for s in (1, 2, 3, 5, 6)}}]})
        return httpx.Response(200, json=_load("ratings_005930_2025.json" if year in ("2025", "2026") else "ratings_005930_noyear.json"))
    if code == codes.CODE_RATING_HISTORY:
        return httpx.Response(200, json=_load("history_005930.json") if isu == "005930" else {"block1": []})
    if code == codes.CODE_REPORT_SUMMARY:
        return httpx.Response(200, json=_load("report_summary_005930.json") if isu == "005930" else {"result": []})
    if code == codes.CODE_ISSUE_INFO:
        if isu == "005930":
            return httpx.Response(200, json=_load("issue_005930.json"))
        if isu == "247540":     # 코스닥 — 색인엔 없지만 포털은 안다
            return httpx.Response(200, json={"result": [{"isu_cd": "247540", "isur_cd": "24754",
                                                         "rep_isu_cd": "KR7247540008", "com_abbrv": "에코프로비엠"}]})
        return httpx.Response(200, json={"result": []})
    if code == codes.CODE_REPORT_LIST:
        return httpx.Response(200, json=_load("reports_005930.json") if isu == "005930" else {"result": []})
    if code == codes.CODE_GOV_DISCLOSURES:
        return httpx.Response(200, json=_load("disclosures_005930.json") if isu == "005930" else {"result": []})
    if code == codes.CODE_COMPANY_LIST:
        return httpx.Response(200, json=_load("list_2025_head.json") if year == "2025" else {"result": []})
    return httpx.Response(500, text="unrouted")


def make_dart_index(api_key: str) -> DartCorpIndex:
    http = httpx.AsyncClient(base_url=OPENDART_BASE_URL, transport=httpx.MockTransport(route))
    return DartCorpIndex(http, api_key=api_key)


@pytest.fixture
def dart_index() -> DartCorpIndex:
    """키가 있는 DART 명부(fixture 15행). 이 머신의 환경변수와 무관하게 늘 같은 상태."""
    index = make_dart_index("test")
    set_index(index)
    yield index
    set_index(None)


@pytest.fixture
def krx_client(dart_index) -> KrxEsgClient:
    http = httpx.AsyncClient(base_url=codes.BASE_URL, transport=httpx.MockTransport(route))
    client = KrxEsgClient(http, min_interval=0.0)
    set_client(client)
    yield client
    set_client(None)
