"""부록 표 파서 정답집 대조 (network) — `scripts/report_tables_golden.json` 의 값이 파서 결과에서 어디에 나오는지 센다.

    uv run python scripts/eval_report_tables.py --pdf-dir /tmp/sr-pdf     # PDF 28건(약 350MB)을 받아 두고 재사용

분류: correct(검사 통과 칸 · 맞는 해 · 목표 열 아님) / wrong_year(검사 통과 칸인데 해가 다르거나 목표 열에서만) /
flagged(검사에 걸린 행의 원문 줄에만) / not_found(그 쪽 표 어디에도 없음 — 표 밖 값이면 정상).
**wrong_year 가 하나라도 있으면 실패(종료 코드 1)** — 조용히 틀린 값이 새로 생긴 것이다(CLAUDE.md 규칙 14).
KIND 에서 받을 때는 1.5초 간격(규칙 1). 이미 받은 파일은 다시 받지 않는다.
"""

from __future__ import annotations

import argparse
import collections
import io
import json
import logging
import pathlib
import re
import sys
import time

import httpx
import pdfplumber

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from open_esg_korea.krx.kind import USER_AGENT  # noqa: E402
from open_esg_korea.pdf import extract, tables  # noqa: E402

_PLAN = re.compile(r"목표(?!관리)|계획|전망|예상|추정|Target|target|Goal|Plan")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf-dir", required=True, type=pathlib.Path)
    ap.add_argument("--golden", type=pathlib.Path, default=pathlib.Path(__file__).with_name("report_tables_golden.json"))
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()
    logging.getLogger("pdfminer").setLevel(logging.ERROR)
    args.pdf_dir.mkdir(parents=True, exist_ok=True)
    items = json.loads(args.golden.read_text())["items"]

    pdfs = {i["code"]: i["pdf"] for i in items}
    with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=180, follow_redirects=True) as http:
        for code, url in pdfs.items():
            path = args.pdf_dir / f"{code}.pdf"
            if not path.exists():
                path.write_bytes(http.get(url).raise_for_status().content)
                time.sleep(1.5)

    parsed: dict[tuple[str, int], list[tables.Table]] = {}
    counts: collections.Counter[str] = collections.Counter()
    for it in items:
        key = (it["code"], it["page"])
        if key not in parsed:
            with pdfplumber.open(io.BytesIO((args.pdf_dir / f"{it['code']}.pdf").read_bytes())) as pdf:
                parsed[key] = tables.parse_page(extract._words(pdf.pages[it["page"] - 1]), it["page"])
        tabs = parsed[key]
        years = {c.key: c.year for t in tabs for c in t.columns}
        cells = [col for t in tabs for r in t.rows if r.status == "ok" for col, v in r.values.items() if v == it["value"]]
        if any(years.get(c) == it["year"] and not _PLAN.search(c) for c in cells):
            kind = "correct"
        elif cells:
            kind = "wrong_year"
        elif any(it["value"] in r.line.split() for t in tabs for r in t.rows if r.status == "check"):
            kind = "flagged"
        else:
            kind = "not_found"
        counts[kind] += 1
        if args.verbose and kind != "correct":
            print(f"{kind:<10} {it['company']:<10} {it['metric']:<12} p{it['page']:<4} {it['value']} (기대 {it['year']}) {cells[:2]}")
    total = sum(counts.values())
    print(f"값 {total}개 — " + " · ".join(f"{k} {counts[k]} ({counts[k] / total:.0%})"
                                         for k in ("correct", "wrong_year", "flagged", "not_found")))
    return 1 if counts["wrong_year"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
