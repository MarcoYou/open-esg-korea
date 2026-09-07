"""DART 고유번호 명부 — zip 해석 · 상장사 필터 · 7일 캐시 · 키 없음 · XML 오류."""

from __future__ import annotations

import pytest

from open_esg_korea.dart.corp_codes import DartClientError, parse_listed
from tests.conftest import corpcode_zip, make_dart_index


def test_parse_keeps_only_rows_with_a_six_digit_stock_code():
    rows = parse_listed(corpcode_zip())
    codes = {r["isu_cd"] for r in rows}
    assert "247540" in codes and "005930" in codes
    assert all(len(c) == 6 and c.isdigit() for c in codes)
    assert not any(r["name"] == "농협금융지주" for r in rows)      # 비상장(stock_code 공백)
    eco = next(r for r in rows if r["isu_cd"] == "247540")
    assert eco == {"isu_cd": "247540", "name": "에코프로비엠", "eng_name": "ECOPRO BM CO.,LTD.",
                   "corp_code": "01160363", "modify_date": "20250714"}


def test_non_zip_xml_error_is_a_dart_client_error():
    body = b'<?xml version="1.0"?><result><status>020</status><message>limit</message></result>'
    with pytest.raises(DartClientError) as exc:
        parse_listed(body)
    assert exc.value.status == "020" and "limit" in str(exc.value)


def test_garbage_is_a_dart_client_error_not_a_crash():
    with pytest.raises(DartClientError):
        parse_listed(b"PK\x03\x04not really a zip")


async def test_listed_downloads_once_and_serves_from_memory():
    index = make_dart_index("test")
    first = await index.listed()
    second = await index.listed()
    assert first is second and index.downloads == 1
    assert index.peek() is first
    assert index.stats() == {"enabled": True, "downloads": 1, "listed": len(first)}


async def test_without_a_key_the_index_is_disabled_and_silent():
    index = make_dart_index("")
    assert index.enabled is False
    assert await index.listed() == [] and index.peek() == [] and index.downloads == 0


async def test_bad_key_surfaces_as_dart_client_error():
    index = make_dart_index("bad")
    with pytest.raises(DartClientError) as exc:
        await index.listed()
    assert exc.value.status == "010"


def test_peek_is_empty_before_the_first_download():
    assert make_dart_index("test").peek() == []
