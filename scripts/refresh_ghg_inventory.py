#!/usr/bin/env python3
"""국가 온실가스 인벤토리 스냅샷 갱신 — 공공데이터포털 CSV → open_esg_korea/data/ghg_inventory.json

Why: 인벤토리는 연 1회 발표되는 작은 표(분야 160여 행 × 1990~최근년)라 서버가 실시간으로 받을 이유가 없다.
포털 파일은 업로드마다 atchFileId 가 바뀌므로 URL 을 인자로 받는다(https://www.data.go.kr/data/15049589/fileData.do 의 다운로드 버튼).

사용:  python3 scripts/refresh_ghg_inventory.py --csv inventory.csv   (내려받은 파일)
       python3 scripts/refresh_ghg_inventory.py --url 'https://www.data.go.kr/cmm/cmm/fileDownload.do?atchFileId=FILE_…&fileDetailSn=1'
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import io
import json
import pathlib
import sys
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "open_esg_korea" / "data" / "ghg_inventory.json"


def to_float(v: str) -> float | None:
    """수치가 아니면 None — 기밀(C)·미발생(NO)·미산정(NE)·타항목포함(IE)·'NO, NE' 같은 조합 표기."""
    try:
        return float(v.replace(",", "")) if v.strip() and v.strip()[0] in "0123456789-." and v.strip() != "-" else None
    except ValueError:
        return None



def parse(text: str) -> dict:
    rows = list(csv.reader(io.StringIO(text.lstrip("﻿"))))
    header = rows[0]
    years = [h.strip() for h in header[1:] if h.strip().isdigit()]
    series: list[dict] = []
    for r in rows[1:]:
        if not r or not r[0].strip():
            continue
        values = {}
        for y, v in zip(years, r[1:]):
            values[y] = to_float(v)
        series.append({"category": r[0].strip(), "values": values})
    if len(series) < 100 or len(years) < 30:
        raise SystemExit(f"인벤토리 모양이 기대와 다릅니다: 행 {len(series)} · 연도 {len(years)}")
    return {"meta": {"source": "기후에너지환경부 온실가스종합정보센터 국가 온실가스 인벤토리 배출량 (공공데이터포털 15049589)",
                     "unit": "kt CO2-eq", "years": years, "fetched_at": dt.date.today().isoformat(),
                     "markers": "C=기밀 NO=미발생 NE=미산정 IE=타항목포함 → null", "rows": len(series)},
            "series": series}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv")
    ap.add_argument("--url")
    args = ap.parse_args()
    if args.csv:
        raw = pathlib.Path(args.csv).read_bytes()
    elif args.url:
        req = urllib.request.Request(args.url, headers={"User-Agent": "open-esg-korea refresh script",
                                                        "Referer": "https://www.data.go.kr/"})
        with urllib.request.urlopen(req, timeout=120) as resp:
            raw = resp.read()
    else:
        print("--csv 또는 --url 이 필요합니다.", file=sys.stderr)
        return 2
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("cp949")
    payload = parse(text)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=0), encoding="utf-8")
    print(f"저장: {OUT} · 행 {len(payload['series'])} · {payload['meta']['years'][0]}~{payload['meta']['years'][-1]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
