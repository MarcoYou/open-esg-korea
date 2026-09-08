"""호스트 허용 목록이 **바인딩한 포트를 따라가는지**. network 0.

포트를 바꿨을 때 `/health` 는 열리는데 `/mcp` 만 「Invalid Host header」로 막히던 것을 잡는다
(실측 2026-09-09). 목록만 보는 단위 검사로는 그때도 통과했을 것이므로 — 목록에 8000 이 들어
있었으니 — 실제로 앱에 넣고 그 포트의 Host 헤더로 두드려 본다.
"""

from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from open_esg_korea.server import allowed_hosts, bind_port, build_app

_INIT = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
         "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                    "clientInfo": {"name": "binding", "version": "0"}}}
_HDRS = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}


def test_default_port_allowlist():
    assert bind_port() == 8000
    assert allowed_hosts() == ["localhost:8000", "127.0.0.1:8000", "0.0.0.0:8000"]


def test_custom_port_moves_the_whole_allowlist(monkeypatch):
    """규칙: 포트는 한 곳(`bind_port`)에서 온다 — 세 항목이 다 같이 움직여야 한다."""
    monkeypatch.setenv("FASTMCP_PORT", "8123")
    assert allowed_hosts() == ["localhost:8123", "127.0.0.1:8123", "0.0.0.0:8123"]
    assert "localhost:8000" not in allowed_hosts()


def test_extra_hosts_still_append(monkeypatch):
    monkeypatch.setenv("FASTMCP_ALLOWED_HOSTS", " esg.example.com , esg.example.com:443 ,, ")
    hosts = allowed_hosts()
    assert hosts[:3] == ["localhost:8000", "127.0.0.1:8000", "0.0.0.0:8000"]
    assert hosts[3:] == ["esg.example.com", "esg.example.com:443"]      # 공백·빈 항목은 버린다


def test_extra_hosts_append_on_a_custom_port_too(monkeypatch):
    monkeypatch.setenv("FASTMCP_PORT", "8123")
    monkeypatch.setenv("FASTMCP_ALLOWED_HOSTS", "esg.example.com")
    assert allowed_hosts() == ["localhost:8123", "127.0.0.1:8123", "0.0.0.0:8123", "esg.example.com"]


@pytest.mark.parametrize("port", ["8000", "8123"])
def test_mcp_answers_on_the_bound_port_and_rejects_others(krx_client, monkeypatch, port):
    """이게 진짜 회귀 검사다 — 목록이 아니라 **앱이** 그 포트를 받아야 한다."""
    monkeypatch.setenv("FASTMCP_PORT", port)
    with TestClient(build_app()) as c:
        ok = c.post("/mcp", json=_INIT, headers={**_HDRS, "Host": f"localhost:{port}"})
        assert ok.status_code == 200, f"바인딩한 포트인데 막혔다: {ok.text[:200]}"
        # 보호가 켜져 있는 것도 같이 확인한다 — 「다 열어서」 통과하면 의미가 없다.
        assert c.post("/mcp", json=_INIT, headers={**_HDRS, "Host": "evil.example.com"}).status_code == 421


def test_regression_wrong_port_is_rejected(krx_client, monkeypatch):
    """8123 으로 띄웠으면 8000 은 남의 host 다 — 목록이 따라 움직였다는 반대쪽 증거."""
    monkeypatch.setenv("FASTMCP_PORT", "8123")
    with TestClient(build_app()) as c:
        assert c.post("/mcp", json=_INIT, headers={**_HDRS, "Host": "localhost:8000"}).status_code == 421
