#!/usr/bin/env python3
"""governance_report 실서버 스모크 — fixture 가 아니라 진짜 KRX·KIND 를 친다.

사용: uv run python scripts/smoke_governance_report.py [회사명 …]
기본 회사: 삼성전자(일반 서식) · KB금융(연차보고서 갈음) · 에코프로비엠(코스닥, 미제출)

왜 따로 두나: `pytest` 는 network 0 이라 「원문 화면이 바뀌었는지」를 못 잡는다. KIND 는 비공식 화면이라
서식·선택자가 바뀌면 조용히 0건이 된다 — 그때 파싱 개수가 뚝 떨어지는 것을 여기서 본다.

TLS 주의: 회사망처럼 TLS 를 가로채는 프록시 뒤에서는 httpx 기본 CA 번들로 검증이 실패한다
(`CERTIFICATE_VERIFY_FAILED: self-signed certificate in certificate chain`). Windows 에서는
`ssl.enum_certificates` 로 OS 인증서 저장소를 그대로 얹어 준다 — **검증을 끄지 않는다.**
"""
from __future__ import annotations

import asyncio
import ssl
import sys
import time

import httpx

from open_esg_korea.krx import codes
from open_esg_korea.krx.client import KrxEsgClient, set_client
from open_esg_korea.krx.kind import KindClient, set_kind_client
from open_esg_korea.services.governance_report_payload import build_governance_report_payload

DEFAULT_COMPANIES = ["삼성전자", "KB금융", "에코프로비엠"]
UA = "open-esg-korea/0.1 (smoke)"


def ssl_context() -> ssl.SSLContext:
    """기본 CA + (윈도우면) OS 저장소. 가로채기 프록시 뒤에서도 검증을 켠 채 붙기 위한 것."""
    ctx = ssl.create_default_context()
    if sys.platform != "win32":
        return ctx
    for store in ("ROOT", "CA"):
        for cert, encoding, trust in ssl.enum_certificates(store):
            if encoding == "x509_asn" and trust is True:
                try:
                    ctx.load_verify_locations(cadata=ssl.DER_cert_to_PEM_cert(cert))
                except ssl.SSLError:
                    pass                      # 만료·중복 인증서는 넘긴다
    return ctx


def wire(ctx: ssl.SSLContext) -> None:
    set_client(KrxEsgClient(httpx.AsyncClient(
        base_url=codes.BASE_URL, verify=ctx, timeout=30.0,
        headers={"User-Agent": UA, "Referer": f"{codes.BASE_URL}/", "X-Requested-With": "XMLHttpRequest"})))
    set_kind_client(KindClient(httpx.AsyncClient(
        verify=ctx, follow_redirects=True,
        headers={"User-Agent": UA, "Referer": f"{codes.KIND_BASE_URL}/"},
        timeout=httpx.Timeout(connect=10.0, read=180.0, write=30.0, pool=10.0))))


async def run(companies: list[str]) -> int:
    wire(ssl_context())
    failed = 0
    for company in companies:
        started = time.monotonic()
        try:
            payload = await build_governance_report_payload(company, scope="notes")
        except Exception as exc:                              # noqa: BLE001 — 스모크는 무엇이 터졌는지만 알면 된다
            print(f"✗ {company}: {type(exc).__name__}: {exc}")
            failed += 1
            continue
        data = payload["data"]
        counts = data.get("counts") or {}
        filing = data.get("filing") or {}
        took = time.monotonic() - started
        print(f"{'·' if payload['status'] == 'no_data' else '✓'} {company}: status={payload['status']} "
              f"form={data.get('form', '-')} 접수={filing.get('acpt_no', '-')} "
              f"원칙={counts.get('principles', 0)} 표={counts.get('tables', 0)} "
              f"사유={counts.get('notes', 0)} 준수율={data.get('compliance_rate', '-')} ({took:.1f}s)")
        for w in payload["warnings"]:
            print(f"    ! {w}")
        # 일반 서식인데 원칙이 28개가 아니면 화면이 바뀐 것이다 — 0건은 「미준수」가 아니라 「못 읽음」.
        if data.get("form") == "gov_report" and counts.get("principles") != 28:
            print(f"    ✗ 세부원칙이 28개가 아니다({counts.get('principles')}) — 서식이 바뀌었는지 원문을 확인하라.")
            failed += 1
    return failed


if __name__ == "__main__":
    sys.exit(asyncio.run(run(sys.argv[1:] or DEFAULT_COMPANIES)))
