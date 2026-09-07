"""외부(KRX·DART) 실패를 크래시 대신 정상 응답으로 낮추는 안전망 — tool 래퍼 한 곳에서 쓴다.

코드버그(KeyError 등)는 여기 집합에 없다 — 그대로 터져서 error_kind=crash 로 보이게 한다.
"""

from __future__ import annotations

import asyncio
import json

import httpx

from open_esg_korea.dart.corp_codes import DartClientError
from open_esg_korea.gir.client import GirClientError
from open_esg_korea.krx.client import KrxClientError

EXTERNAL_ERRORS = (KrxClientError, DartClientError, GirClientError, httpx.HTTPError, asyncio.TimeoutError, TimeoutError)


def classify(exc: BaseException) -> tuple[str, str]:
    if isinstance(exc, (httpx.TimeoutException, asyncio.TimeoutError, TimeoutError)):
        return ("timeout", "외부 소스(KRX ESG 포털·DART·GIR) 응답이 지연되고 있습니다. 잠시 후 다시 시도하세요.")
    if isinstance(exc, httpx.HTTPStatusError) and exc.response is not None:
        code = exc.response.status_code
        if code in (403, 429):
            return ("blocked", "외부 소스가 요청을 거부했습니다(차단 또는 과호출). 한 번에 여러 회사를 "
                               "조회 중이라면 건수를 줄이고 간격을 두세요.")
        if 500 <= code < 600:
            return ("upstream_5xx", "외부 소스가 일시적 오류(5xx)를 반환했습니다. 잠시 후 다시 시도하세요.")
    if isinstance(exc, KrxClientError):
        return ("bad_response", str(exc) or "KRX ESG 포털 응답을 해석할 수 없습니다.")
    if isinstance(exc, DartClientError):
        return ("bad_response", str(exc) or "DART 응답을 해석할 수 없습니다.")
    if isinstance(exc, GirClientError):
        return ("bad_response", str(exc) or "GIR 응답을 해석할 수 없습니다.")
    return ("transient", "외부 소스 조회가 일시적으로 실패했습니다. 잠시 후 다시 시도하세요.")


def degrade_response(tool_name: str, fmt: str, exc: BaseException) -> str:
    kind, msg = classify(exc)
    marker = f"[degraded={kind}]"
    if (fmt or "md").lower() == "json":
        return json.dumps({"tool": tool_name, "status": "error", "warnings": [msg],
                           "data": {"error_class": type(exc).__name__, "error_kind": kind,
                                    "marker": marker}}, ensure_ascii=False, indent=2)
    return f"# {tool_name}\n\n{msg}\n\n{marker}"
