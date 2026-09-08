"""네트워크 0 — KRX·DART 응답을 fixture 로 대신하는 httpx.MockTransport.

실제 클라이언트(`KrxEsgClient`·`DartCorpIndex`)를 그대로 쓴다. 가짜는 전송층 하나뿐이라 캐시·간격·파싱 경로가
전부 테스트를 거친다. DART 명부는 XML fixture 를 요청 시점에 zip 으로 싸서 돌려준다(실제 응답 모양).
"""

from __future__ import annotations

import io
import json
import pathlib
import zipfile
from urllib.parse import parse_qs, unquote, urlparse

import httpx
import pytest

from open_esg_korea.dart.corp_codes import BUNDLE_PATH, CORP_CODE_PATH, OPENDART_BASE_URL, DartCorpIndex, set_index
from open_esg_korea.gir import codes as gcodes
from open_esg_korea.gir.client import GirClient, set_gir_client
from open_esg_korea.krx import codes
from open_esg_korea.krx.client import KrxEsgClient, set_client
from open_esg_korea.krx.kind import KindClient, set_kind_client

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


def gir_route(request: httpx.Request) -> httpx.Response:
    """GIR 명세서(HTML)·ETRS(CSV cp949) — 2024/3차·4차만 fixture, 그 밖의 해는 빈 표."""
    url = urlparse(str(request.url))
    qs = {k: v[0] for k, v in parse_qs(url.query).items()}
    if url.netloc == "www.gir.go.kr" and url.path == gcodes.STATEMENT_PATH:
        if qs.get("condition.year") == "2024":
            return httpx.Response(200, text=(FIX / "gir_statement_2024_subset.html").read_text(encoding="utf-8"))
        return httpx.Response(200, text='<html><table><tr><th>법인명</th></tr></table></html>')
    if url.netloc == "etrs.gir.go.kr" and url.path == gcodes.CERTIFIED_PATH:
        if qs.get("condition.pfYy") == "2024":
            return httpx.Response(200, content=(FIX / "etrs_certified_2024_subset.csv").read_bytes(),
                                  headers={"content-type": "text/csv; charset=MS949"})
        return httpx.Response(200, content="번호,부문,업종,업체명,이행연도,배출권 할당량(톤),인증 배출량(톤)\r\n".encode("cp949"))
    if url.netloc == "etrs.gir.go.kr" and url.path == gcodes.ALLOCATION_PATH:
        period = qs.get("condition.plPeriDgr")
        if period in ("3", "4"):
            return httpx.Response(200, content=(FIX / f"etrs_allocation_p{period}_subset.csv").read_bytes(),
                                  headers={"content-type": "text/csv; charset=MS949"})
        return httpx.Response(200, content="번호,부문,업종,업체명,유상여부\r\n".encode("cp949"))
    return httpx.Response(404, text="no such gir page")



def _read(name: str) -> str:
    return (FIX / name).read_text(encoding="utf-8")


#: 접수번호 → 뷰어 fixture. 삼성전자 2025(일반 서식)와 KB금융 2025(연차보고서 갈음) 두 갈래.
KIND_VIEWERS = {"20250530001005": "kind_viewer_005930_2025.html",
                "20260601000268": "kind_viewer_005930_2026.html",
                "20250305001136": "kind_viewer_105560_2025.html",
                "20250627000633": "kind_viewer_sr_005930_2025.html",
                "20260626000871": "kind_viewer_sr_005930_2026.html"}
#: 문서번호 → 경로 응답(`parent.setPath(...)`) fixture.
KIND_CONTENTS = {"20250530001923": "kind_contents_005930_2025.html",
                 "20260601000417": "kind_contents_005930_2026.html",
                 "20250226002153": "kind_contents_105560_2025.html",
                 "20250623001134": "kind_contents_sr_005930_2025.html",
                 "20250627000755": "kind_contents_sr_att_005930_2025.html",
                 "20260623000638": "kind_contents_sr_005930_2026.html",
                 "20260623000652": "kind_contents_sr_att_005930_2026.html"}
#: 본문 주소 끝 → 본문 fixture. 삼성전자 본문은 원칙 3개만 남긴 subset(원본 5.7MB).
KIND_BODIES = {"/external/2025/05/30/001005/20250530001923/99667.htm": "kind_gov_005930_2025_subset.html",
               "/external/2026/06/01/000268/20260601000417/99667.htm": "kind_gov_005930_2026_subset.html",
               "/external/2025/03/05/001136/20250226002153/99669.htm": "kind_gov_105560_2025.html",
               "/external/2025/06/27/000633/20250623001134/61979.htm": "kind_sr_notice_005930_2025.html",
               "/external/2025/06/27/000633/20250627000755/99998.htm": "kind_sr_attach_005930_2025.html",
               "/external/2026/06/26/000871/20260623000638/61979.htm": "kind_sr_notice_005930_2026.html",
               "/external/2026/06/26/000871/20260623000652/99998.htm": "kind_sr_attach_005930_2026.html"}


#: 첨부 PDF — 삼성전자 2025 보고서에서 3쪽(표지·서술·수치 표)만 뽑은 진짜 PDF 343KB.
KIND_FILES = {"/external/2025/06/27/000633/20250627000755/"
              "%EC%82%BC%EC%84%B1%EC%A0%84%EC%9E%90%20%EC%A7%80%EC%86%8D%EA%B0%80%EB%8A%A5%EA%B2%BD%EC%98%81%EB%B3%B4%EA%B3%A0%EC%84%9C_2025.pdf":
              "sr_005930_2025_3pages.pdf"}


def kind_route(request: httpx.Request) -> httpx.Response:
    """KIND 원문 뷰어 — ①뷰어 ②경로 ③본문 세 단을 그대로 흉내낸다."""
    url = urlparse(str(request.url))
    qs = {k: v[0] for k, v in parse_qs(url.query).items()}
    if url.path == codes.KIND_SEARCH_PATH:
        # 공시 검색은 POST 본문이다 — 종목코드·기간·제목으로 갈라 준다(맞는 조합에만 결과가 있다).
        form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
        if (form.get("repIsuSrtCd") == "A005930" and form.get("fromDate", "").startswith("2026")
                and codes.KIND_SEARCH_SUSTAINABILITY in form.get("reportNm", "")):
            return httpx.Response(200, text=_read("kind_search_sr_005930_2026.html"))
        return httpx.Response(200, text='<table><tr><td>조회된 내용이 없습니다.</td></tr></table>')
    if url.path == codes.KIND_VIEWER_PATH:
        if qs.get("method") == "search":
            name = KIND_VIEWERS.get(qs.get("acptno", ""))
            #: 모르는 접수번호에도 200 을 준다 — 옵션 없는 껍데기(실제 KIND 도 404 를 주지 않는다).
            return httpx.Response(200, text=_read(name) if name else "<html><body>no such document</body></html>")
        if qs.get("method") == "searchContents":
            name = KIND_CONTENTS.get(qs.get("docNo", ""))
            return httpx.Response(200, text=_read(name) if name else "<html><script>/* no setPath */</script></html>")
    name = KIND_BODIES.get(url.path)
    if name:
        return httpx.Response(200, text=_read(name), headers={"content-type": "text/html"})
    name = KIND_FILES.get(url.path) or KIND_FILES.get(unquote(url.path))
    if name:
        data = (FIX / name).read_bytes()
        rng = request.headers.get("Range")
        if rng:                                   # 크기만 물어보는 1바이트 Range (KIND 는 HEAD 에 405 를 준다)
            return httpx.Response(206, content=data[:1], headers={
                "content-type": "application/pdf", "content-range": f"bytes 0-0/{len(data)}"})
        return httpx.Response(200, content=data, headers={"content-type": "application/pdf"})
    return httpx.Response(404, text="no such kind page")


def route(request: httpx.Request) -> httpx.Response:
    url = urlparse(str(request.url))
    if url.netloc.endswith("opendart.fss.or.kr"):
        return dart_route(request)
    if url.netloc.endswith("gir.go.kr"):
        return gir_route(request)
    if url.netloc.endswith("kind.krx.co.kr"):
        return kind_route(request)
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
        by_company = {"005930": "disclosures_005930.json", "105560": "disclosures_105560.json"}
        name = by_company.get(isu)
        return httpx.Response(200, json=_load(name) if name else {"result": []})
    if code == codes.CODE_COMPANY_LIST:
        return httpx.Response(200, json=_load("list_2025_head.json") if year == "2025" else {"result": []})
    return httpx.Response(500, text="unrouted")


def make_dart_index(api_key: str, *, bundle: bool = False) -> DartCorpIndex:
    """기본은 번들 없이(fixture 15행만) — 저장소 스냅샷 내용에 테스트가 흔들리지 않게. `bundle=True` 면 실제 스냅샷을 쓴다."""
    http = httpx.AsyncClient(base_url=OPENDART_BASE_URL, transport=httpx.MockTransport(route))
    return DartCorpIndex(http, api_key=api_key, bundle_path=BUNDLE_PATH if bundle else None)


@pytest.fixture
def dart_index() -> DartCorpIndex:
    """키가 있는 DART 명부(fixture 15행, 번들 없음). 이 머신의 환경변수와 무관하게 늘 같은 상태."""
    index = make_dart_index("test")
    set_index(index)
    yield index
    set_index(None)


@pytest.fixture
def gir_client() -> GirClient:
    client = GirClient(httpx.AsyncClient(transport=httpx.MockTransport(route)), min_interval=0.0)
    set_gir_client(client)
    yield client
    set_gir_client(None)


@pytest.fixture
def krx_client(dart_index, gir_client, kind_client) -> KrxEsgClient:
    """KIND 도 함께 갈아 끼운다 — sustainability_reports 가 공시 원문을 곁들여 읽기 때문이다(network 0 유지)."""
    http = httpx.AsyncClient(base_url=codes.BASE_URL, transport=httpx.MockTransport(route))
    client = KrxEsgClient(http, min_interval=0.0)
    set_client(client)
    yield client
    set_client(None)


@pytest.fixture
def kind_client() -> KindClient:
    client = KindClient(httpx.AsyncClient(transport=httpx.MockTransport(route)), min_interval=0.0)
    set_kind_client(client)
    yield client
    set_kind_client(None)
