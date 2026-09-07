"""회사 식별 — 이름·종목코드 → KRX ESG 포털의 `isu_cd`.

두 겹 색인:
1. **포털 검색기**(빈 검색어 → 유가증권 834사). 24시간 캐시. 여기 있으면 보고서·지배구조 화면까지 다 있다.
2. **DART 고유번호 명부**(`dart/corp_codes.py`). 포털에서 못 찾았을 때만 부른다 — 코스닥 회사명은
   여기서 종목코드를 얻고, 포털에는 그 코드로 등급표를 묻는다. 정식 상호(「현대자동차」)로 유가증권을 찾을 때도 돕는다.
   키가 있으면 실시간 명부, 없으면 저장소에 동봉한 스냅샷(월 1회 갱신)이다 — 그래서 키 없이도 코스닥이 된다.

6자리 숫자는 코드로 보고 색인을 거치지 않는다. DART 가 실패하면 그 사실만 경고로 남기고 포털만으로 답한다
— 보조 색인이 죽었다고 유가증권 조회까지 죽으면 안 된다.
"""

from __future__ import annotations

import asyncio
import difflib
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

import httpx

from open_esg_korea.dart.corp_codes import STALE_AFTER_DAYS, DartClientError, DartCorpIndex, get_index
from open_esg_korea.krx.client import KrxEsgClient, get_client
from open_esg_korea.services.contracts import AnalysisStatus

_CODE_RE = re.compile(r"^\(?(\d{6})\)?")
_LEGAL_RE = re.compile(r"(?:\(주\)|（주）|㈜|㈐|\(유\)|주식회사|유한회사|유한책임회사|합자회사|합명회사"
                       r"|사회복지법인|재단법인|사단법인|학교법인|의료법인)")
_NON_WORD_RE = re.compile(r"[^0-9a-z가-힣&]+")

# 알파벳의 한글 음차 — GIR·공고 헤더는 「에스케이하이닉스」, 포털·DART 는 「SK하이닉스」(OPM 실측 유형). 긴 표기부터.
_LETTER_KO = {"에이치": "h", "더블유": "w", "더블류": "w", "제트": "z", "엑스": "x", "에스": "s", "에프": "f",
              "에이": "a", "제이": "j", "케이": "k", "브이": "v", "와이": "y", "아이": "i", "아르": "r",
              "엘": "l", "엠": "m", "엔": "n", "오": "o", "피": "p", "큐": "q", "알": "r", "티": "t", "유": "u",
              "비": "b", "씨": "c", "디": "d", "지": "g"}
_LETTER_KO_ORDER = sorted(_LETTER_KO, key=len, reverse=True)

# 낱말 브랜드의 영문↔한글 — 글자 음차로는 못 잇는 것만(「POSCO홀딩스」↔「포스코홀딩스」). 포털·DART 는 영문, GIR 은 한글.
_WORD_ALIASES = {"posco": "포스코", "naver": "네이버", "kakao": "카카오", "hanwha": "한화", "doosan": "두산",
                 "hyundai": "현대", "samsung": "삼성", "lotte": "롯데", "kumho": "금호", "hanjin": "한진",
                 "hanon": "한온", "coway": "코웨이", "kepco": "한국전력", "hanil": "한일", "daewoo": "대우",
                 "hite": "하이트", "amorepacific": "아모레퍼시픽", "hanssem": "한샘", "hanmi": "한미", "orion": "오리온"}
_DART_ERRORS = (DartClientError, httpx.HTTPError, asyncio.TimeoutError, TimeoutError)

OUTSIDE_INDEX_WARNING = ("포털 검색기(유가증권) 색인 밖의 종목입니다 — 코스닥 등. 등급표는 조회되지만 "
                         "보고서·지배구조 화면은 비어 있을 수 있습니다.")


def normalize(name: str) -> str:
    s = unicodedata.normalize("NFKC", name or "").casefold()
    s = _LEGAL_RE.sub("", s)
    return _NON_WORD_RE.sub("", s)


def name_keys(name: str) -> set[str]:
    """이름 대조용 키 집합 — 정규화 이름 + 앞머리 한글 음차를 알파벳으로 되돌린 변형(2글자 이상).

    「에스케이하이닉스」→ {에스케이하이닉스, sk하이닉스}. 「엔」처럼 알파벳이자 낱말 첫 글자인 음절이 있어 어디까지
    글자로 읽을지 하나로 못 정하므로 길이별 변형을 모두 만든다(OPM 방식). 양쪽 키가 하나라도 겹치면 같은 이름으로 본다.
    """
    n = normalize(name)
    keys = {n} if n else set()
    for en, ko in _WORD_ALIASES.items():
        if n.startswith(en):
            keys.add(ko + n[len(en):])
        elif n.startswith(ko):
            keys.add(en + n[len(ko):])
    letters: list[str] = []
    i = 0
    while i < len(n):
        for kw in _LETTER_KO_ORDER:
            if n.startswith(kw, i):
                letters.append(_LETTER_KO[kw])
                i += len(kw)
                break
        else:
            break
        if len(letters) >= 2:
            keys.add("".join(letters) + n[i:])
    return keys


@dataclass(slots=True)
class CompanyResolution:
    status: AnalysisStatus
    query: str
    selected: dict[str, Any] | None = None       # {"isu_cd","name","in_index","match","corp_code"}
    candidates: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


async def load_index(client: KrxEsgClient | None = None) -> list[dict[str, str]]:
    client = client or get_client()
    rows = await client.finder("")
    return [{"isu_cd": r.get("isu_cd", ""), "name": r.get("com_abbrv", "")} for r in rows
            if r.get("isu_cd")]


async def _dart_rows(dart: DartCorpIndex, warnings: list[str]) -> list[dict[str, str]]:
    """보조 색인. 실시간 → 번들 순으로 시도하고, 둘 다 안 되면 경고 한 줄 남기고 빈 목록."""
    if not dart.enabled:
        return []
    try:
        rows = await dart.listed()
    except _DART_ERRORS as exc:
        warnings.append(f"DART 고유번호 명부를 불러오지 못해 코스닥 회사명 검색을 건너뜁니다 ({type(exc).__name__}). "
                        "코스닥 종목은 6자리 종목코드로 조회하세요.")
        return []
    if dart.source == "bundle":
        age = dart.bundle_age_days()
        if age is not None and age > STALE_AFTER_DAYS:
            warnings.append(f"상장사 명부 스냅샷이 {age}일 전({dart.bundle_date()}) 것입니다 — 그 뒤 상장·개명한 회사는 "
                            "회사명으로 찾지 못할 수 있습니다. 종목코드로 조회하거나 스냅샷을 갱신하세요.")
    return rows


def _pick(row: dict[str, Any], *, by_code: dict[str, dict], dart_by_code: dict[str, dict], match: str) -> dict[str, Any]:
    """선택된 행을 공통 모양으로. 포털 색인에 있으면 포털 약명을 쓴다(후속 화면이 그 이름을 쓴다)."""
    code = row["isu_cd"]
    portal = by_code.get(code)
    dart = dart_by_code.get(code)
    return {"isu_cd": code, "name": (portal or row)["name"], "in_index": portal is not None, "match": match,
            "corp_code": (dart or {}).get("corp_code") or None}


def _candidate(row: dict[str, Any], *, by_code: dict[str, dict], dart_by_code: dict[str, dict]) -> dict[str, Any]:
    code = row["isu_cd"]
    portal = by_code.get(code)
    return {"isu_cd": code, "name": (portal or row)["name"], "in_index": portal is not None,
            "corp_code": (dart_by_code.get(code) or {}).get("corp_code") or None}


def _names_of(row: dict[str, Any]) -> list[str]:
    return [normalize(n) for n in (row.get("name", ""), row.get("eng_name", "")) if n]


async def resolve_company(query: str, client: KrxEsgClient | None = None,
                          dart: DartCorpIndex | None = None) -> CompanyResolution:
    client = client or get_client()
    dart = dart or get_index()
    q = (query or "").strip()
    if not q:
        return CompanyResolution(AnalysisStatus.ERROR, q, warnings=["회사명 또는 6자리 종목코드를 입력하세요."])

    index = await load_index(client)
    by_code = {r["isu_cd"]: r for r in index}
    warnings: list[str] = []

    m = _CODE_RE.match(q)
    if m and (len(q) == 6 or q.startswith("(")):
        code = m.group(1)
        dart_by_code = {r["isu_cd"]: r for r in dart.peek()}    # 코드 직행은 DART 적재를 기다리지 않는다
        if code in by_code:
            return CompanyResolution(AnalysisStatus.EXACT, q, selected=_pick(
                by_code[code], by_code=by_code, dart_by_code=dart_by_code, match="code"))
        info = await client.issue_info(code)
        if info and info.get("com_abbrv"):
            sel = _pick({"isu_cd": code, "name": info["com_abbrv"]}, by_code=by_code, dart_by_code=dart_by_code,
                        match="code")
            return CompanyResolution(AnalysisStatus.EXACT, q, selected=sel, warnings=[OUTSIDE_INDEX_WARNING])
        return CompanyResolution(AnalysisStatus.ERROR, q,
                                 warnings=[f"종목코드 {code} 를 KRX ESG 포털에서 찾지 못했습니다."])

    nq = normalize(q)
    if not nq:
        return CompanyResolution(AnalysisStatus.ERROR, q, warnings=["회사명을 해석할 수 없습니다."])

    exact = [r for r in index if normalize(r["name"]) == nq]
    if len(exact) == 1:
        dart_by_code = {r["isu_cd"]: r for r in dart.peek()}
        return CompanyResolution(AnalysisStatus.EXACT, q, selected=_pick(
            exact[0], by_code=by_code, dart_by_code=dart_by_code, match="exact"))

    # 포털에 정확히 없다 → 이제 DART 명부를 (필요하면 내려받아) 연다.
    dart_rows = await _dart_rows(dart, warnings)
    dart_by_code = {r["isu_cd"]: r for r in dart_rows}
    pick = lambda row, match: _pick(row, by_code=by_code, dart_by_code=dart_by_code, match=match)  # noqa: E731
    cand = lambda row: _candidate(row, by_code=by_code, dart_by_code=dart_by_code)  # noqa: E731

    dart_exact = [r for r in dart_rows if nq in _names_of(r)]
    if len(dart_exact) == 1:
        sel = pick(dart_exact[0], "exact")
        if not sel["in_index"]:
            warnings.append(OUTSIDE_INDEX_WARNING)
        return CompanyResolution(AnalysisStatus.EXACT, q, selected=sel, warnings=warnings)
    if len(dart_exact) > 1:
        return CompanyResolution(AnalysisStatus.AMBIGUOUS, q, candidates=[cand(r) for r in dart_exact[:10]],
                                 warnings=warnings)

    partial: dict[str, dict] = {}
    for r in index:
        n = normalize(r["name"])
        if nq in n or n in nq:
            partial[r["isu_cd"]] = r
    for r in dart_rows:
        if r["isu_cd"] in partial:
            continue
        if any(nq in n or n in nq for n in _names_of(r)):
            partial[r["isu_cd"]] = r
    if len(partial) == 1:
        (r,) = partial.values()
        sel = pick(r, "partial")
        warnings.append(f"「{q}」를 **{sel['name']}**({sel['isu_cd']})로 추정했습니다 — 이름이 정확히 일치하지 "
                        "않습니다. 다른 회사라면 종목코드로 다시 물어보세요.")
        if not sel["in_index"]:
            warnings.append(OUTSIDE_INDEX_WARNING)
        return CompanyResolution(AnalysisStatus.EXACT, q, selected=sel, warnings=warnings)
    if partial:
        rows = sorted(partial.values(), key=lambda r: (r["isu_cd"] not in by_code,
                                                       not normalize(r["name"]).startswith(nq), len(r["name"])))
        return CompanyResolution(AnalysisStatus.AMBIGUOUS, q, candidates=[cand(r) for r in rows[:10]],
                                 warnings=warnings)

    names: dict[str, dict] = {}
    for r in list(dart_rows) + index:          # 같은 코드는 포털 행이 나중에 덮어 이름이 포털 약명이 된다
        for n in _names_of(r):
            names[n] = r
    close = difflib.get_close_matches(nq, list(names), n=5, cutoff=0.6)
    cands = [cand(names[c]) for c in close]
    hint = "코스닥 종목이면 6자리 종목코드로 조회하세요."
    if dart_rows:
        scope = ("KRX ESG 포털 검색기(유가증권)·DART 상장사 명부" if dart.source == "live" else
                 f"KRX ESG 포털 검색기(유가증권)·상장사 명부 스냅샷({dart.bundle_date()})")
        if dart.source != "live":
            hint += " 그 뒤 상장·개명한 회사면 OPENDART_API_KEY 를 설정해 실시간 명부로 찾을 수 있습니다."
    else:
        scope = "KRX ESG 포털 검색기(유가증권)"
        hint += " OPENDART_API_KEY 를 설정하면 코스닥 회사명 검색도 됩니다."
    warnings.append(f"「{q}」에 해당하는 회사를 {scope}에서 찾지 못했습니다. {hint}")
    return CompanyResolution(AnalysisStatus.ERROR, q, candidates=cands, warnings=warnings)


def company_block(res: CompanyResolution) -> dict[str, Any]:
    sel = res.selected or {}
    return {"isu_cd": sel.get("isu_cd", ""), "name": sel.get("name", ""),
            "match": sel.get("match", ""), "in_portal_index": sel.get("in_index", False),
            "corp_code": sel.get("corp_code")}
