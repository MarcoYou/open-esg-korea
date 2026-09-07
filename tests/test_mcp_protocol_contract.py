"""프로토콜 계약 — 프로덕션이 실제로 서빙하는 앱(`build_app()`)에 대고 잰다. network 0."""

from __future__ import annotations

import json

import pytest
from starlette.testclient import TestClient

from open_esg_korea.server import allowed_hosts, build_app

_INIT = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
         "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                    "clientInfo": {"name": "contract", "version": "0"}}}
_HDRS = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
EXPECTED_TOOLS = {"company", "esg_ratings", "sustainability_reports", "sustainability_report_text", "governance_indicators",
                  "governance_policies", "governance_report", "esg_disclosures", "esg_screener", "ghg_emissions", "ghg_industry", "ghg_national_inventory"}


@pytest.fixture()
def client(krx_client):
    with TestClient(build_app()) as c:
        yield c


def _post(client, body, host="localhost:8000"):
    return client.post("/mcp", json=body, headers={**_HDRS, "Host": host})


def _result_text(r):
    return r.json()["result"]["content"][0]["text"]


def test_allowed_host_is_served_and_foreign_host_rejected(client):
    assert _post(client, _INIT).status_code == 200
    assert _post(client, _INIT, host="evil.example.com").status_code == 421
    assert "localhost:8000" in allowed_hosts()


def test_stateless_json_responses(client):
    a = _post(client, _INIT)
    b = _post(client, {**_INIT, "id": 2})
    assert a.status_code == b.status_code == 200
    assert "application/json" in a.headers.get("content-type", "")


def test_tools_list_over_the_wire(client):
    r = _post(client, {"jsonrpc": "2.0", "id": 3, "method": "tools/list", "params": {}})
    tools = r.json()["result"]["tools"]
    assert {t["name"] for t in tools} == EXPECTED_TOOLS
    for t in tools:
        assert t["description"].lstrip().startswith("desc:"), t["name"]


def test_tools_guide_resource_lists_every_tool(client):
    r = _post(client, {"jsonrpc": "2.0", "id": 4, "method": "resources/read",
                       "params": {"uri": "oek://tools_guide"}})
    text = r.json()["result"]["contents"][0]["text"]
    for name in EXPECTED_TOOLS:
        assert f"## {name}" in text


def test_esg_ratings_call_renders_markdown_with_source(client):
    r = _post(client, {"jsonrpc": "2.0", "id": 5, "method": "tools/call",
                       "params": {"name": "esg_ratings", "arguments": {"company": "삼성전자", "year": 2025}}})
    text = _result_text(r)
    assert r.json()["result"].get("isError") is not True
    assert "| KCGS |" in text and "**A**" in text and "출처: KRX ESG 포털" in text


def test_esg_ratings_json_format_is_the_envelope(client):
    r = _post(client, {"jsonrpc": "2.0", "id": 6, "method": "tools/call",
                       "params": {"name": "esg_ratings", "arguments": {"company": "005930", "year": 2025, "format": "json"}}})
    payload = json.loads(_result_text(r))
    assert payload["tool"] == "esg_ratings" and payload["status"] == "exact"
    assert {"source", "license", "warnings", "data"} <= set(payload)


def test_ambiguous_company_does_not_crash_and_lists_candidates(client):
    r = _post(client, {"jsonrpc": "2.0", "id": 7, "method": "tools/call",
                       "params": {"name": "governance_indicators", "arguments": {"company": "삼성"}}})
    text = _result_text(r)
    assert "후보가 여러 개" in text and "005930" in text


def test_upstream_failure_degrades_instead_of_is_error(client, krx_client, monkeypatch):
    import httpx

    async def boom(*a, **k):
        raise httpx.ConnectError("down")
    monkeypatch.setattr(krx_client, "_throttled_post", boom)
    r = _post(client, {"jsonrpc": "2.0", "id": 8, "method": "tools/call",
                       "params": {"name": "esg_ratings", "arguments": {"company": "삼성전자"}}})
    assert r.json()["result"].get("isError") is not True
    assert "[degraded=" in _result_text(r)


def test_company_kosdaq_name_over_the_wire_carries_corp_code(client):
    r = _post(client, {"jsonrpc": "2.0", "id": 9, "method": "tools/call",
                       "params": {"name": "company", "arguments": {"query": "에코프로비엠", "format": "json"}}})
    payload = json.loads(_result_text(r))
    assert payload["status"] == "exact"
    assert payload["data"]["company"]["isu_cd"] == "247540"
    assert payload["data"]["company"]["corp_code"] == "01160363"
    assert payload["data"]["company"]["in_index"] is False
