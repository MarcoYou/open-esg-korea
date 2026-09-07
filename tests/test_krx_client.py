"""클라이언트 — 캐시·JSON 아님·필드 정규화."""

from __future__ import annotations

import httpx
import pytest

from open_esg_korea.krx import codes
from open_esg_korea.krx.client import KrxClientError, KrxEsgClient
from open_esg_korea.services.contracts import clean
from open_esg_korea.services.esg_ratings import parse_ratings_row


async def test_same_query_hits_cache_not_network(krx_client):
    await krx_client.ratings("005930", 2025)
    await krx_client.ratings("005930", 2025)
    assert krx_client.calls == 1 and krx_client.cache_hits == 1


async def test_non_json_body_is_a_client_error_not_a_crash():
    http = httpx.AsyncClient(base_url=codes.BASE_URL,
                             transport=httpx.MockTransport(lambda r: httpx.Response(200, text="<html>blocked</html>")))
    client = KrxEsgClient(http, min_interval=0.0)
    with pytest.raises(KrxClientError):
        await client.ratings("005930", 2025)


def test_dash_is_null_not_a_grade():
    assert clean("-") is None and clean("") is None and clean(" A+ ") == "A+"


async def test_ratings_row_parses_five_agencies_and_sp_as_int(krx_client):
    rows = await krx_client.ratings("005930", 2025)
    parsed = {r["agency_id"]: r for r in parse_ratings_row(rows[0])}
    assert set(parsed) == {"kcgs", "msci", "kesg", "sp", "sustinvest"}
    assert parsed["kcgs"]["esg"] == "A" and parsed["kcgs"]["e"] == "B+"
    assert parsed["msci"]["esg"] == "AA" and parsed["msci"]["e"] is None
    assert parsed["sp"]["esg"] == 43 and isinstance(parsed["sp"]["esg"], int)
    assert parsed["kcgs"]["attachment"].endswith(".pdf")


async def test_unrated_year_has_no_coverage(krx_client):
    rows = await krx_client.ratings("005930", None)
    assert all(not r["coverage"] for r in parse_ratings_row(rows[0]))
