"""회사 식별 — 이름·종목코드 → KRX ESG 포털의 `isu_cd`.

색인은 포털 검색기가 아는 전체 목록(빈 검색어 → 유가증권 834사)이다. 24시간 캐시.
6자리 숫자는 코드로 보고 색인을 거치지 않는다 — 코스닥 종목은 색인에 없지만 등급 조회는 된다.
"""

from __future__ import annotations

import difflib
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

from open_esg_korea.krx.client import KrxEsgClient, get_client
from open_esg_korea.services.contracts import AnalysisStatus

_CODE_RE = re.compile(r"^\(?(\d{6})\)?")
_LEGAL_RE = re.compile(r"(?:\(주\)|（주）|㈜|주식회사)")
_NON_WORD_RE = re.compile(r"[^0-9a-z가-힣&]+")


def normalize(name: str) -> str:
    s = unicodedata.normalize("NFKC", name or "").casefold()
    s = _LEGAL_RE.sub("", s)
    return _NON_WORD_RE.sub("", s)


@dataclass(slots=True)
class CompanyResolution:
    status: AnalysisStatus
    query: str
    selected: dict[str, Any] | None = None       # {"isu_cd","name","in_index","match"}
    candidates: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


async def load_index(client: KrxEsgClient | None = None) -> list[dict[str, str]]:
    client = client or get_client()
    rows = await client.finder("")
    return [{"isu_cd": r.get("isu_cd", ""), "name": r.get("com_abbrv", "")} for r in rows
            if r.get("isu_cd")]


async def resolve_company(query: str, client: KrxEsgClient | None = None) -> CompanyResolution:
    client = client or get_client()
    q = (query or "").strip()
    if not q:
        return CompanyResolution(AnalysisStatus.ERROR, q, warnings=["회사명 또는 6자리 종목코드를 입력하세요."])

    index = await load_index(client)
    by_code = {r["isu_cd"]: r for r in index}

    m = _CODE_RE.match(q)
    if m and (len(q) == 6 or q.startswith("(")):
        code = m.group(1)
        if code in by_code:
            return CompanyResolution(AnalysisStatus.EXACT, q, selected={
                "isu_cd": code, "name": by_code[code]["name"], "in_index": True, "match": "code"})
        info = await client.issue_info(code)
        if info and info.get("com_abbrv"):
            return CompanyResolution(AnalysisStatus.EXACT, q, selected={
                "isu_cd": code, "name": info["com_abbrv"], "in_index": False, "match": "code"},
                warnings=["포털 검색기(유가증권) 색인 밖의 종목입니다 — 코스닥 등. 등급표는 조회되지만 "
                          "보고서·지배구조 화면은 비어 있을 수 있습니다."])
        return CompanyResolution(AnalysisStatus.ERROR, q,
                                 warnings=[f"종목코드 {code} 를 KRX ESG 포털에서 찾지 못했습니다."])

    nq = normalize(q)
    if not nq:
        return CompanyResolution(AnalysisStatus.ERROR, q, warnings=["회사명을 해석할 수 없습니다."])

    exact = [r for r in index if normalize(r["name"]) == nq]
    if len(exact) == 1:
        return CompanyResolution(AnalysisStatus.EXACT, q, selected={**exact[0], "in_index": True, "match": "exact"})

    partial = [r for r in index if nq in normalize(r["name"]) or normalize(r["name"]) in nq]
    if len(partial) == 1:
        r = partial[0]
        return CompanyResolution(AnalysisStatus.EXACT, q,
                                 selected={**r, "in_index": True, "match": "partial"},
                                 warnings=[f"「{q}」를 **{r['name']}**({r['isu_cd']})로 추정했습니다 — 이름이 "
                                           "정확히 일치하지 않습니다. 다른 회사라면 종목코드로 다시 물어보세요."])
    if partial:
        partial.sort(key=lambda r: (not normalize(r["name"]).startswith(nq), len(r["name"])))
        return CompanyResolution(AnalysisStatus.AMBIGUOUS, q, candidates=partial[:10])

    names = {normalize(r["name"]): r for r in index}
    close = difflib.get_close_matches(nq, list(names), n=5, cutoff=0.6)
    cands = [names[c] for c in close]
    return CompanyResolution(AnalysisStatus.ERROR, q, candidates=cands,
                             warnings=[f"「{q}」에 해당하는 회사를 KRX ESG 포털 검색기(유가증권)에서 찾지 못했습니다. "
                                       "코스닥 종목이면 6자리 종목코드로 조회하세요."])


def company_block(res: CompanyResolution) -> dict[str, Any]:
    sel = res.selected or {}
    return {"isu_cd": sel.get("isu_cd", ""), "name": sel.get("name", ""),
            "match": sel.get("match", ""), "in_portal_index": sel.get("in_index", False)}
