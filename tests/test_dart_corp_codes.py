"""DART 고유번호 명부 — zip 해석 · 상장사 필터 · 7일 캐시 · 번들 폴백 · 키 없음 · XML 오류."""

from __future__ import annotations

import datetime as dt

import httpx
import pytest

from open_esg_korea.dart.corp_codes import DartClientError, load_bundle, parse_listed
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
    assert index.peek() is first and index.source == "live"
    st = index.stats()
    assert st["live_enabled"] is True and st["downloads"] == 1 and st["live_rows"] == len(first) and st["bundle_rows"] == 0


async def test_without_a_key_and_without_a_bundle_the_index_is_disabled_and_silent():
    index = make_dart_index("")
    assert index.enabled is False
    assert await index.listed() == [] and index.peek() == [] and index.downloads == 0


# ── 번들 스냅샷 ──────────────────────────────────────────────────────────────────

def test_bundled_snapshot_is_well_formed():
    b = load_bundle()
    assert b is not None and b["meta"]["rows"] == len(b["rows"]) >= 3000
    codes = [r["isu_cd"] for r in b["rows"]]
    assert len(set(codes)) == len(codes) and all(len(c) == 6 and c.isdigit() for c in codes)
    assert codes == sorted(codes)                                  # 갱신 diff 가 읽히도록 정렬 고정
    assert all(len(r["corp_code"]) == 8 for r in b["rows"])
    assert dt.date.fromisoformat(b["meta"]["fetched_at"])
    assert any(r["name"] == "에코프로비엠" and r["isu_cd"] == "247540" for r in b["rows"])


async def test_without_a_key_the_bundle_serves_names_without_network():
    index = make_dart_index("", bundle=True)
    assert index.enabled is True and index.live_enabled is False
    rows = await index.listed()
    assert index.source == "bundle" and index.downloads == 0 and len(rows) >= 3000
    assert index.peek() is rows


async def test_live_failure_falls_back_to_the_bundle_and_records_the_error():
    index = make_dart_index("down", bundle=True)
    rows = await index.listed()
    assert index.source == "bundle" and len(rows) >= 3000
    assert "HTTPStatusError" in index.last_error


async def test_live_failure_without_a_bundle_raises():
    index = make_dart_index("down")
    with pytest.raises(httpx.HTTPStatusError):
        await index.listed()


async def test_live_wins_over_bundle_when_it_loads():
    index = make_dart_index("test", bundle=True)
    assert index.peek() and index.source == "bundle"                 # 아직 안 내려받았으니 번들
    rows = await index.listed()
    assert index.source == "live" and len(rows) == 14 and index.peek() is rows


def test_missing_bundle_file_is_none_not_a_crash(tmp_path):
    assert load_bundle(tmp_path / "nope.json") is None
    (tmp_path / "bad.json").write_text("{not json", encoding="utf-8")
    assert load_bundle(tmp_path / "bad.json") is None


async def test_bad_key_surfaces_as_dart_client_error():
    index = make_dart_index("bad")
    with pytest.raises(DartClientError) as exc:
        await index.listed()
    assert exc.value.status == "010"


def test_peek_is_empty_before_the_first_download():
    assert make_dart_index("test").peek() == []
