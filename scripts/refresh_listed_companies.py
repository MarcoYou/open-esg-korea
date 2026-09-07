#!/usr/bin/env python3
"""상장사 명부 스냅샷 갱신 — OpenDART corpCode.xml → open_esg_korea/data/listed_companies.json

Why: 코스닥 회사명 검색에 쓰는 「회사명 → 종목코드」 사전을 서버가 키 없이도 갖고 있게 하려고 저장소에 동봉한다.
등급이 아니라 공개 원장이므라 라이선스 문제가 없다. 상호 변경·신규 상장은 드물어 월 1회 갱신으로 충분하다.

사용:  OPENDART_API_KEY=... python3 scripts/refresh_listed_companies.py [--zip corpCode.zip]
       (--zip 을 주면 이미 받아 둔 파일을 쓴다 — 네트워크 없이 재생성)
출력:  바뀐 행 수(추가·삭제·개명)를 stdout 에 요약한다. 변경이 없으면 파일을 건드리지 않는다.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import pathlib
import sys
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from open_esg_korea.dart.corp_codes import OPENDART_BASE_URL, CORP_CODE_PATH, ENV_KEYS, parse_listed  # noqa: E402
from open_esg_korea.dart.corp_codes import BUNDLE_PATH, FIELDS, load_bundle  # noqa: E402


def download(api_key: str) -> bytes:
    url = f"{OPENDART_BASE_URL}{CORP_CODE_PATH}?crtfc_key={api_key}"
    req = urllib.request.Request(url, headers={"User-Agent": "open-esg-korea refresh script"})
    with urllib.request.urlopen(req, timeout=600) as resp:
        return resp.read()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--zip", help="이미 받아 둔 corpCode.xml zip 경로")
    ap.add_argument("--out", default=str(BUNDLE_PATH))
    args = ap.parse_args()

    if args.zip:
        content = pathlib.Path(args.zip).read_bytes()
    else:
        key = next((os.environ.get(k, "").strip() for k in ENV_KEYS if os.environ.get(k, "").strip()), "")
        if not key:
            print(f"환경변수 {' 또는 '.join(ENV_KEYS)} 가 필요합니다.", file=sys.stderr)
            return 2
        content = download(key)

    rows = parse_listed(content)
    if len(rows) < 3000:
        print(f"상장사 행이 {len(rows)}개밖에 없습니다 — 응답이 잘렸거나 형식이 바뀐 듯합니다. 갱신하지 않습니다.", file=sys.stderr)
        return 1
    rows.sort(key=lambda r: r["isu_cd"])

    out = pathlib.Path(args.out)
    old = {r["isu_cd"]: r for r in (load_bundle(out) or {"rows": []})["rows"]} if out.exists() else {}
    new = {r["isu_cd"]: r for r in rows}
    added = sorted(set(new) - set(old))
    removed = sorted(set(old) - set(new))
    renamed = sorted(c for c in set(new) & set(old) if new[c]["name"] != old[c]["name"])
    changed = sorted(c for c in set(new) & set(old) if new[c] != old[c])
    print(f"행 {len(old)} → {len(new)} · 추가 {len(added)} · 삭제 {len(removed)} · 개명 {len(renamed)} · 그 외 변경 {len(changed) - len(renamed)}")
    for c in added[:20]:
        print(f"  + {c} {new[c]['name']}")
    for c in removed[:20]:
        print(f"  - {c} {old[c]['name']}")
    for c in renamed[:20]:
        print(f"  ~ {c} {old[c]['name']} → {new[c]['name']}")
    if old and not (added or removed or changed):
        print("변경 없음 — 파일을 건드리지 않습니다.")
        return 0

    payload = {
        "meta": {"source": f"OpenDART corpCode.xml ({OPENDART_BASE_URL}{CORP_CODE_PATH})",
                 "fetched_at": dt.date.today().isoformat(), "rows": len(rows),
                 "note": "종목코드가 있는 법인만. DART 는 상장폐지 후에도 stock_code 를 남기므로 「있다 = 상장 중」이 아니다.",
                 "fields": list(FIELDS)},
        "rows": [[r[f] for f in FIELDS] for r in rows],
    }
    text = json.dumps(payload["meta"], ensure_ascii=False, indent=1)
    body = ",\n".join(json.dumps(r, ensure_ascii=False) for r in payload["rows"])
    out.write_text("{\n\"meta\": " + text + ",\n\"rows\": [\n" + body + "\n]\n}\n", encoding="utf-8")
    print(f"저장: {out} ({out.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
