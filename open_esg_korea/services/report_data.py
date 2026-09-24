"""지속가능경영보고서 **부록(데이터 장) 표** — 행 후보를 표 모양으로 돌려준다.

`sustainability_report_text` 가 「그 쪽에 뭐라고 썼나」(원문)라면 이 도구는 「그 표를 행·열로」다. 실무에서 가장 많이
하는 일 — 부록 수치 표를 엑셀로 옮기기 — 을 한 번에 하게 한다.

**값은 후보다(규칙 8).** 행마다 검사(열 머리 완결·열 수 일치·붙은 숫자·옆 표 값 섞임·행 이름 유무)를 하고, 모두 통과한
행만 값을 싣는다. 걸린 행은 값을 비우고 그 줄의 원문을 준다. 같은 지표가 한 보고서에 국내/글로벌·시장/지역기반으로
여러 번 나오므로 하나로 고르지 않는다 — 열 머리(경계)·표 제목·각주를 보고 고르는 것은 읽는 쪽이다.

정확도 실측(2026-09-24, 시총 상위 30개사 보고서 28건): 30개사 작업(AI 작업자가 보고서를 읽고 옮긴 값 271개)과 대조해
83%가 검사를 통과한 칸에서 맞는 해로 나왔고, **검사를 통과했는데 해가 틀린 칸은 0**이었다. 10%는 검사에 걸려 원문으로, 7%는 표
밖(본문 요약·검증의견서·합산값)이었다. 데이터 장 390쪽 전체로는 행 8,881개 중 94%가 검사를 통과했다(값 38,738개).
대조는 `scripts/eval_report_tables.py`(정답집 `scripts/report_tables_golden.json`).
"""

from __future__ import annotations

import re
from typing import Any

from open_esg_korea.krx.client import KrxEsgClient
from open_esg_korea.krx.kind import KindClient
from open_esg_korea.pdf import extract
from open_esg_korea.services.contracts import AnalysisStatus
from open_esg_korea.services.report_text import MAX_SNIPPET_PAGES, open_report, page_numbers, page_tables

#: 쪽 범위로 한 번에 풀 수 있는 최대 쪽 수(표는 원문보다 작아서 본문 도구의 5쪽보다 넓게 둔다).
MAX_DATA_PAGES = 12
#: 데이터 장을 못 찾았을 때 「별도로 냈다」는 단서를 찾는 말 — 데이터북·팩트북을 따로 낸 회사(KB금융·삼성바이오로직스).
_SEPARATE_BOOK = ("데이터북", "Data Book", "DataBook", "Factbook", "Fact Book", "팩트북", "ESG Data")

READING_NOTES = [
    "값은 **후보**입니다 — 검사를 모두 통과한 행(`ok`)만 값을 실었습니다. 검사에 걸린 행(`check`)은 값을 비우고 그 줄의 "
    "원문을 줍니다. `sustainability_report_text(page=…)` 로 그 쪽 원문과 대조하세요.",
    "같은 지표가 한 보고서에 여러 번 나옵니다(국내/글로벌, 시장/지역기반, 회사별). 하나로 고르지 않았습니다 — **열 머리**"
    "(연도·경계)와 **표 제목·각주**를 보고 고르세요.",
    "「2025 목표」처럼 목표·계획 열은 열 머리에 그렇게 적혀 있습니다. 표시 없는 같은 해 열이 실적입니다.",
]


def _squash(text: str) -> str:
    return re.sub(r"\s+", "", text)


def _row_matches(needle: str, table: dict[str, Any], row: dict[str, Any]) -> bool:
    return any(needle in _squash(x) for x in (row["label"], row.get("parent", ""), table["title"]))


async def build_report_data_payload(company: str, *, find: str = "", page: int | str | None = None,
                                    year: int | None = None, client: KrxEsgClient | None = None,
                                    kind: KindClient | None = None) -> dict[str, Any]:
    opened = await open_report("sustainability_report_data", company, year=year, client=client, kind=kind,
                               out={"find": find, "page": page})
    env, out, doc = opened.env, opened.out, opened.doc
    if doc is None:
        return env.to_dict()
    assert opened.kind is not None

    if page is not None:
        wanted = page_numbers(page) if isinstance(page, int) else _wide_pages(page)
        if isinstance(wanted, str):
            env.status = AnalysisStatus.NO_DATA
            env.warnings.append(wanted)
            env.data = out
            return env.to_dict()
        pages = [p for p in wanted if 1 <= p <= len(doc.pages)]
        if not pages:
            env.status = AnalysisStatus.NO_DATA
            env.warnings.append(f"{wanted[0]}쪽부터는 이 보고서에 없습니다(전체 {len(doc.pages)}쪽).")
            env.data = out
            return env.to_dict()
    elif doc.section:
        pages = doc.section
    else:
        env.status = AnalysisStatus.NO_DATA
        env.warnings.append("수치 표가 모인 데이터 장을 찾지 못했습니다 — 「표가 없다」가 아니라 「이 방법으로 못 찾았다」입니다. "
                            "수치가 본문 장에 흩어진 보고서이거나(찾기 → page= 로 그 쪽 표를 푸세요) 데이터북을 따로 냈을 수 "
                            "있습니다.")
        hints = [h for term in _SEPARATE_BOOK for h in extract.search(doc.pages, term)][:MAX_SNIPPET_PAGES]
        if hints:
            out["separate_book_mentions"] = [{"page": h["page"], "snippet": h["snippets"][0]} for h in hints]
            env.warnings.append("본문에 데이터북·팩트북을 따로 냈다는 말이 있는 쪽: "
                                + ", ".join(str(h["page"]) for h in hints) + " — 공시 첨부에 없으면 회사 사이트를 보세요.")
        env.data = out
        return env.to_dict()

    tables: list[dict[str, Any]] = []
    unreadable: list[str] = []
    for p in pages:
        parsed, reason = await page_tables(opened.url, doc, p, opened.kind)
        if parsed is None:
            unreadable.append(f"{p}쪽 — {reason}")
            continue
        tables += [t.to_dict() for t in parsed]
    if unreadable:
        env.warnings.append("표로 풀지 못한 쪽이 있습니다(평문은 `sustainability_report_text` 로): " + " · ".join(unreadable))

    needle = _squash(find)
    if needle:
        for t in tables:
            t["rows"] = [r for r in t["rows"] if _row_matches(needle, t, r)]
        tables = [t for t in tables if t["rows"]]
        if not tables:
            env.warnings.append(f"「{find}」가 들어간 행을 찾지 못했습니다(행 이름·상위 행·표 제목에서, 공백 무시). "
                                "표기가 다를 수 있습니다 — 「없다」고 단정하지 마세요.")

    rows = [r for t in tables for r in t["rows"]]
    out.update({"pages": [pages[0], pages[-1]] if pages else None, "tables": tables,
                "counts": {"tables": len(tables), "rows": len(rows),
                           "ok_rows": sum(r["status"] == "ok" for r in rows),
                           "check_rows": sum(r["status"] == "check" for r in rows),
                           "values": sum(len(r["values"]) for r in rows)}})
    if doc.section and page is None:
        out["scope_note"] = (f"데이터 장 {doc.section[0]}–{doc.section[-1]}쪽(자동 판정). 본문 장에 있는 표는 page= 로 "
                             "따로 푸세요.")
    env.warnings += READING_NOTES
    env.data = out
    env.next_actions = [
        f'sustainability_report_text(company="{company}", page=…) — 그 쪽 원문과 대조',
        f'sustainability_report_data(company="{company}", find="에너지") — 행 이름으로 좁히기',
        f'ghg_emissions(company="{company}") — 정부 명세서(GIR) 배출량과 대조',
    ]
    return env.to_dict()


def _wide_pages(page: str) -> list[int] | str:
    """쪽 범위 — 표 도구는 12쪽까지. 형식 검사는 본문 도구와 같다."""
    m = re.match(r"^\s*(\d+)\s*(?:[-~–]\s*(\d+))?\s*$", str(page))
    if not m:
        return f'page 는 쪽 번호(140) 또는 범위("139-148")로 주세요 — 받은 값: {page!r}'
    lo, hi = int(m.group(1)), int(m.group(2) or m.group(1))
    if hi < lo:
        return f"범위의 끝({hi}쪽)이 시작({lo}쪽)보다 앞입니다."
    if hi - lo + 1 > MAX_DATA_PAGES:
        return f"한 번에 {MAX_DATA_PAGES}쪽까지 풉니다({lo}–{hi}쪽은 {hi - lo + 1}쪽) — 나눠서 부르세요."
    return list(range(lo, hi + 1))
