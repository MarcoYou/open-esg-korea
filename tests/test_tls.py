"""TLS 컨텍스트 — 사내망 뒤에서도 **검증을 켠 채** 붙는다(network 0).

이 파일이 지키는 것 둘: 「안 되면 검증을 끈다」로 도망가지 않는 것, 그리고 네 클라이언트가
빠짐없이 같은 컨텍스트를 쓰는 것(한 곳만 빠지면 그 소스만 조용히 죽는다).
"""

from __future__ import annotations

import pathlib
import ssl

import certifi

from open_esg_korea.tls import ssl_context


def test_verification_stays_on():
    ctx = ssl_context()
    assert ctx.verify_mode is ssl.CERT_REQUIRED and ctx.check_hostname is True


def test_trusts_more_than_certifi_alone():
    """진짜 원인은 httpx 가 OS 저장소 대신 certifi 를 본다는 것이었다 — 사내망 루트가 거기 없다.
    (실측 2026-09-08: certifi 121장 → 연결 실패 / 기본 컨텍스트 384장 → 302 OK)"""
    certifi_only = len(ssl.create_default_context(cafile=certifi.where()).get_ca_certs())
    assert len(ssl_context().get_ca_certs()) >= certifi_only


def test_every_client_uses_it():
    """규칙 3 — 한 곳만 빠져도 그 소스만 조용히 죽는다."""
    root = pathlib.Path(__file__).resolve().parents[1] / "open_esg_korea"
    for rel in ("krx/client.py", "krx/kind.py", "gir/client.py", "dart/corp_codes.py"):
        assert "verify=ssl_context()" in (root / rel).read_text(encoding="utf-8"), rel
