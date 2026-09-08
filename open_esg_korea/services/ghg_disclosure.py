"""보고서가 공시한 온실가스 수치를 **범위와 함께** 집어 온다 — GIR 명세서 옆에 놓기 위한 것.

왜 필요한가(2026-09-08 실측): GIR 과 보고서는 **범위만 맞추면 사실상 같은 값**이다. 회사가 GIR 에 낸
명세서를 보고서에도 싣기 때문이다(포스코홀딩스 1톤·현대차 10톤·SK하이닉스 0.10%·LG화학 0.50% 차이).
벌어지는 건 표지에 박히는 숫자가 대개 **글로벌**이라서다(삼성전자 9%).

그래서 이 모듈은 「보고서 값 = N」을 만들지 않는다. **한 보고서 안에 값이 여럿이기 때문이다** —
SK하이닉스 2024년은 셋이다: 4,843,611(국내·지역기반·NF3 제외) · 5,502,136(글로벌·시장기반) ·
5,717,404(국내 + NF3). 어느 것인지 말하지 않고 숫자만 주면 그 답은 틀린 것이나 마찬가지다.

대신 **원문 발췌 + 범위 축**을 준다. 축은 셋:
  경계        국내 규제대상 / 국내 전체 / 글로벌
  Scope 2 방식 지역기반(location) / 시장기반(market)
  선택 항목    NF3 포함 여부
"""

from __future__ import annotations

import re
from typing import Any

#: 무엇에 대한 수치인가. 앞의 것부터 맞춰 본다(「Scope 1+2」가 「Scope 1」보다 먼저).
_KIND_PATTERNS = [
    ("scope12", re.compile(r"Scope\s*1\s*[+&,·]\s*2|Scope\s*1\s*및\s*2|직/?간접[^\n]{0,6}배출")),
    ("scope3", re.compile(r"Scope\s*3")),
    ("scope1", re.compile(r"Scope\s*1|직접\s*배출|직접\s*온실가스")),
    ("scope2", re.compile(r"Scope\s*2|간접\s*배출|간접\s*온실가스")),
]
#: 범위 축 — 발췌 안에 이 말이 있으면 그 축이 정해진 것으로 본다.
_BASIS = {
    "글로벌": re.compile(r"글로벌|해외\s*법인|해외\s*공장|전\s*사업장|연결\s*기준"),
    "국내": re.compile(r"국내"),
    "시장기반": re.compile(r"시장\s*기반|market[\s-]*based"),
    "지역기반": re.compile(r"지역\s*기반|location[\s-]*based"),
    "NF3": re.compile(r"NF3|NF₃|삼불화질소"),
    "검증의견서": re.compile(r"검증\s*의견서|배출권거래제|인증에\s*관한\s*지침"),
}
#: 수치. 쉼표 묶음(1,455,283)과 한글 만 단위(1,455만) 둘 다 쓴다.
_VALUE_RE = re.compile(r"\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?\s*만\s*톤")
_WS_RE = re.compile(r"\s+")


def _snippet(text: str, at: int, before: int = 90, after: int = 220) -> str:
    return _WS_RE.sub(" ", text[max(0, at - before): at + after]).strip()


#: 범위 단서는 표 제목·각주·검증범위처럼 **발췌 창 밖**에 적히는 일이 많다(SK하이닉스 p87 「국내사업장」).
#: 그래서 basis 는 보여줄 발췌보다 넓은 문맥에서 찾는다.
_BASIS_BEFORE, _BASIS_AFTER = 300, 700


def collect_scope_mentions(pages: list[str], *, max_per_kind: int = 4) -> list[dict[str, Any]]:
    """[{kind, page, basis, snippet}] — 수치가 함께 있는 대목만. 값을 파싱하지 않는다.

    `basis` 가 비어 있으면 **범위를 알 수 없다는 뜻**이다 — 그 발췌만으로 GIR 과 비교하면 안 된다.
    """
    found: list[dict[str, Any]] = []
    seen: set[tuple[str, int]] = set()
    for page_no, text in enumerate(pages, start=1):
        flat = _WS_RE.sub(" ", text)
        claimed: list[tuple[int, int]] = []        # 넓은 종류(Scope 1+2)가 차지한 자리
        for kind, pattern in _KIND_PATTERNS:
            for m in pattern.finditer(flat):
                # 「Scope 1+2」 안의 「Scope 1」을 따로 세면 두 배 가까이 틀린다.
                if any(lo <= m.start() < hi for lo, hi in claimed):
                    continue
                window = _snippet(flat, m.start())
                if not _VALUE_RE.search(window):
                    continue                       # 서술만 있고 수치가 없는 대목은 넘긴다
                if (kind, page_no) in seen:
                    break                          # 한 쪽에서 같은 종류는 한 번만
                seen.add((kind, page_no))
                context = flat[max(0, m.start() - _BASIS_BEFORE): m.start() + _BASIS_AFTER]
                found.append({"kind": kind, "page": page_no, "snippet": window,
                              "basis": [name for name, rx in _BASIS.items() if rx.search(context)]})
                break
            if kind == "scope12":
                claimed = [(m.start(), m.end()) for m in pattern.finditer(flat)]
    order = {k: i for i, (k, _) in enumerate(_KIND_PATTERNS)}
    found.sort(key=lambda f: (order[f["kind"]], -len(f["basis"]), f["page"]))
    out: list[dict[str, Any]] = []
    for kind, _ in _KIND_PATTERNS:
        out.extend([f for f in found if f["kind"] == kind][:max_per_kind])
    return out


def basis_summary(mentions: list[dict[str, Any]]) -> dict[str, Any]:
    """어떤 범위 축이 보고서에 나타나는지 — 「이 회사는 값을 몇 가지로 쓰는가」의 실마리."""
    axes = {name: sorted({m["page"] for m in mentions if name in m["basis"]}) for name in _BASIS}
    return {name: pages for name, pages in axes.items() if pages}


#: 응답에 늘 싣는 읽기 주의. 값이 아니라 **어떻게 읽어야 하는지**를 말한다.
READING_NOTES = [
    "GIR 명세서는 **국내 배출권거래제 대상 사업장**의 검증된 규제 기준 배출량(직접+간접)이다.",
    "보고서 표지·요약에 나오는 수치는 대개 **글로벌**이라 GIR 과 다르다 — 같은 값을 다르게 센 것이 아니라 "
    "범위가 다른 것이다(실측: 삼성전자 9% 차이).",
    "범위(경계·Scope 2 지역/시장기반·NF3 포함 여부)를 맞추면 두 소스는 사실상 같다 "
    "(실측 2024년: 포스코홀딩스 1톤·현대차 10톤·SK하이닉스 0.10%·LG화학 0.50% 차이).",
    "한 보고서 안에 값이 여럿일 수 있다(SK하이닉스 2024년은 셋) — 발췌의 `basis` 를 보고 고르라.",
    "Scope 3 는 GIR 에 없다. 보고서가 유일한 출처이고 검증 범위도 회사마다 다르다.",
]
