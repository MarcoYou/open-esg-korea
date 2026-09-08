#!/usr/bin/env python3
"""GICS 산업분류 스냅샷 갱신 — KRX 지수 포털 → open_esg_korea/data/krx_gics.json

Why: 「산업군별로 보기」에 쓸 「종목코드 → 경제섹터·산업군」 사전을 서버가 키 없이 갖고 있게 하려고 동봉한다.
분류는 분기 정도에만 바뀌므로 스냅샷으로 충분하고, 조회 때마다 지수 포털을 두드리지 않는다(호스트가 또 다르고
OTP·쿠키가 필요하다).

사용:  python3 scripts/refresh_krx_gics.py [--date 20260804] [--markets STK,KSQ]
출력:  바뀐 종목 수(추가·삭제·이동)를 요약한다. 변경이 없으면 파일을 건드리지 않는다.

휴장일에는 빈 응답이 온다 — `--fallback-days` 만큼 하루씩 거슬러 올라가며 자료가 있는 날을 찾는다
(월간 워크플로가 1일에 도는데 그날이 주말·공휴일일 수 있다). 실제로 쓴 날짜는 출력과 메타에 남는다.

원본: 유건호 리서치의 `collect_krx_gics.py`(2026-08, low_pbr_screen). 엔드포인트·OTP 흐름은 그대로 쓰고,
      저장소 스냅샷 형식과 KOSDAQ 수집·TLS 처리를 더했다.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import ssl
import sys
import time
import urllib.parse
import urllib.request
from http.cookiejar import CookieJar

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from open_esg_korea.krx import codes  # noqa: E402
from open_esg_korea.services.gics import SNAPSHOT_PATH, FIELDS  # noqa: E402


def ssl_context() -> ssl.SSLContext:
    """TLS 를 가로채는 사내망 뒤에서도 **검증을 켠 채** 붙는다(윈도우 인증서 저장소를 얹는다)."""
    ctx = ssl.create_default_context()
    if sys.platform != "win32":
        return ctx
    for store in ("ROOT", "CA"):
        for cert, encoding, trust in ssl.enum_certificates(store):
            if encoding == "x509_asn" and trust is True:
                try:
                    ctx.load_verify_locations(cadata=ssl.DER_cert_to_PEM_cert(cert))
                except ssl.SSLError:
                    pass
    return ctx


class GicsClient:
    """OTP 를 먼저 받아야 데이터를 준다 — 쿠키를 물고 다닌다."""

    def __init__(self, delay: float = 0.3) -> None:
        self.delay = delay
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(CookieJar()),
            urllib.request.HTTPSHandler(context=ssl_context()),
        )
        self.headers = {"User-Agent": "open-esg-korea refresh script (+https://github.com/MarcoYou/open-esg-korea)",
                        "Referer": codes.GICS_STOCK_PAGE, "X-Requested-With": "XMLHttpRequest"}

    def _post(self, url: str, data: dict[str, str]) -> str:
        body = urllib.parse.urlencode(data).encode()
        req = urllib.request.Request(url, data=body, headers=self.headers)
        with self.opener.open(req, timeout=60) as resp:
            payload = resp.read()
        time.sleep(self.delay)
        return payload.decode("utf-8-sig")

    def start(self) -> None:
        with self.opener.open(urllib.request.Request(codes.GICS_STOCK_PAGE, headers=self.headers), timeout=60) as r:
            r.read()

    def query(self, name: str, bld: str, **params: str) -> list[dict]:
        code = self._post(f"{codes.GICS_BASE_URL}{codes.GICS_OTP_PATH}", {"name": name, "bld": bld}).strip()
        raw = self._post(f"{codes.GICS_BASE_URL}{codes.GICS_DATA_PATH}", {**params, "code": code})
        try:
            body = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise SystemExit(f"KRX 지수 포털이 JSON 이 아닌 것을 돌려줬습니다. 앞부분: {raw[:200]!r}") from exc
        first = next(iter(body.values()), [])
        return first if isinstance(first, list) else []


def collect(client: GicsClient, date: str, markets: list[str]) -> list[list[str]]:
    rows: list[list[str]] = []
    seen: set[str] = set()
    for market in markets:
        options = client.query("selectbox", codes.GICS_OPTION_BLD,
                               mkt_tp_cd=market, gics_ind_grp_cd="", date=date)
        groups = [o for o in options if str(o.get("value", "")).isdigit() and len(str(o["value"])) == 4]
        print(f"[{date} {codes.GICS_MARKETS[market]}] 산업군 {len(groups)}개", flush=True)
        for group in groups:
            group_code = str(group["value"])
            label = str(group.get("label", ""))
            sector_name, _, group_name = label.partition("(")
            stocks = client.query("form", codes.GICS_STOCK_BLD,
                                  mkt_tp_cd=market, gics_ind_grp_cd=group_code, date=date)
            for stock in stocks:
                isu = str(stock.get("isu_cd", "")).strip()
                if not isu or isu in seen:
                    continue                      # 같은 종목이 두 시장에 나오지는 않는다 — 나오면 첫 것을 쓴다
                seen.add(isu)
                rows.append([isu, str(stock.get("isu_abbr", "")).strip(), codes.GICS_MARKETS[market],
                             group_code[:2], sector_name.strip(), group_code, group_name.rstrip(")").strip()])
    return sorted(rows)


def main() -> int:
    ap = argparse.ArgumentParser(description="GICS 산업분류 스냅샷을 갱신합니다.")
    ap.add_argument("--date", default=dt.date.today().strftime("%Y%m%d"), help="조회일자 YYYYMMDD (기본: 오늘)")
    ap.add_argument("--markets", default="STK,KSQ", help="STK=KOSPI, KSQ=KOSDAQ (기본: 둘 다)")
    ap.add_argument("--delay", type=float, default=0.3, help="요청 간격(초)")
    ap.add_argument("--fallback-days", type=int, default=5,
                    help="그 날짜에 자료가 없으면 며칠까지 거슬러 올라갈지 (기본 5 — 연휴 대비)")
    args = ap.parse_args()

    markets = [m.strip().upper() for m in args.markets.split(",") if m.strip()]
    unknown = [m for m in markets if m not in codes.GICS_MARKETS]
    if unknown:
        raise SystemExit(f"모르는 시장 코드: {unknown}")

    client = GicsClient(delay=args.delay)
    client.start()
    asked = dt.datetime.strptime(args.date, "%Y%m%d").date()
    rows: list[list[str]] = []
    used = args.date
    for back in range(max(0, args.fallback_days) + 1):
        used = (asked - dt.timedelta(days=back)).strftime("%Y%m%d")
        rows = collect(client, used, markets)
        if rows:
            if back:
                print(f"{args.date} 에 자료가 없어 {used} 로 물러섰습니다(휴장일).")
            break
    if not rows:
        raise SystemExit(f"{args.date} 부터 {args.fallback_days}일을 거슬러도 한 종목도 받지 못했습니다 — "
                         "긴 연휴이거나 화면이 바뀌었거나 이 IP 가 막혔습니다.")

    old = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8")) if SNAPSHOT_PATH.exists() else {"rows": []}
    before = {r[0]: r[5] for r in old.get("rows", [])}
    after = {r[0]: r[5] for r in rows}
    added = sorted(set(after) - set(before))
    removed = sorted(set(before) - set(after))
    moved = sorted(c for c in set(before) & set(after) if before[c] != after[c])
    if not (added or removed or moved) and old.get("rows"):
        print(f"변경 없음 ({len(rows):,}종목) — 파일을 건드리지 않습니다.")
        return 0

    SNAPSHOT_PATH.write_text(json.dumps({
        "meta": {"source": codes.GICS_STOCK_PAGE, "as_of": used,
                 "fetched_at": dt.date.today().isoformat(), "rows": len(rows),
                 "markets": [codes.GICS_MARKETS[m] for m in markets],
                 "note": codes.GICS_NOTICE, "fields": FIELDS},
        "rows": rows,
    }, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{len(rows):,}종목 저장 — 추가 {len(added)} · 삭제 {len(removed)} · 산업군 이동 {len(moved)}")
    if moved[:5]:
        print("  이동 예:", ", ".join(f"{c} {before[c]}→{after[c]}" for c in moved[:5]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
