#!/usr/bin/env python3
"""KRX ESG 포털 비공식 엔드포인트 프로브.

사용: python scripts/probe_krx.py 005930 [2025]
표준 라이브러리만 사용. 응답 스키마가 바뀌었는지 확인하는 용도.
"""
import json
import sys
import urllib.parse
import urllib.request

BASE = "https://esg.krx.co.kr"
DATA = f"{BASE}/contents/99/ESG99000001.jspx"
HEADERS = {
    "User-Agent": "open-esg-korea/0.1 (probe)",
    "Referer": f"{BASE}/",
    "X-Requested-With": "XMLHttpRequest",
}

CODES = {
    "ratings": "02/02010000/esg02010000_01",
    "rating_history": "02/02010000/esg02010000_09",
    "report_summary": "02/02010000/esg02010000_04",
    "issue_info": "02/02010000/esg02010000_05",
    "sustainability_reports": "02/02030000/esg02030000_01",
    "governance_disclosures": "02/02040000/esg02040000_01",
}


def post(url: str, params: dict) -> dict:
    body = urllib.parse.urlencode(params).encode()
    req = urllib.request.Request(url, data=body, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def probe(isu_cd: str, year: str) -> dict:
    out = {}
    for name, code in CODES.items():
        params = {"code": code, "bldcode": code, "isu_cd": isu_cd, "sch_yy": year,
                  "fr_work_dt": f"{int(year)-2}0101", "to_work_dt": f"{year}1231",
                  "sch_tp": "N", "curPage": "1"}
        out[name] = post(DATA, params)
    for name, path in {
        "governance_core_indicators": "/contents/02/02040100/ESG02040100.jspx",
        "governance_policies": "/contents/02/02040200/ESG02040200.jspx",
    }.items():
        out[name] = post(f"{BASE}{path}", {"isu_cd": isu_cd, "sch_yy": year})
    return out


if __name__ == "__main__":
    isu = sys.argv[1] if len(sys.argv) > 1 else "005930"
    yy = sys.argv[2] if len(sys.argv) > 2 else "2025"
    print(json.dumps(probe(isu, yy), ensure_ascii=False, indent=2))
