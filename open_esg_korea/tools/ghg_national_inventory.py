"""ghg_national_inventory — 국가 온실가스 인벤토리(분야·부문별, 1990~) 시계열."""

from __future__ import annotations

from open_esg_korea.services.contracts import as_pretty_json
from open_esg_korea.services.ghg import build_ghg_inventory_payload
from open_esg_korea.tools._shared import dash, footer, head, num


def _table(rows: list[dict], years: list[str]) -> list[str]:
    lines = ["| 분야 | " + " | ".join(years) + " | 변화 |", "|---|" + "---|" * (len(years) + 1)]
    for r in rows:
        vals = " | ".join(num(r["values_kt"].get(y)) for y in years)
        ch = r["change_pct"]
        lines.append(f"| {r['category']} | {vals} | {dash(f'{ch:+.1f}%' if ch is not None else None)} |")
    return lines


def _render(payload: dict) -> str:
    d = payload["data"]
    lines = head(f"국가 온실가스 인벤토리 — {payload['subject']}", payload)
    if payload["status"] == "error":
        return "\n".join(lines + footer(payload))
    lines.append(f"단위 {d['unit']} (천 톤) · 연도 {d['years'][0]}~{d['years'][-1]}")
    lines.append("")
    if "overview" in d:
        lines += _table(d["overview"], d["years"])
        lines += ["", f"> {d['note']}"]
    else:
        if d["matches"]:
            lines += _table(d["matches"], d["years"])
            if d["matches_total"] > len(d["matches"]):
                lines.append(f"\n({d['matches_total']}개 중 {len(d['matches'])}개)")
    lines += footer(payload)
    return "\n".join(lines)


def register_tools(mcp):

    @mcp.tool()
    async def ghg_national_inventory(find: str = "", years: int = 5, format: str = "md") -> str:
        """desc: 국가 온실가스 인벤토리 — 총배출량·순배출량과 5개 분야(에너지·산업공정·농업·LULUCF·폐기물), find 로 세부 부문(철강·시멘트·화학·도로수송 등) 시계열. 1990~최근 공표년, kt CO₂-eq.
        when: "한국 전체 배출량 추이", "철강 산업 국가 배출량", "산업공정 배출 비중", 회사 배출량을 국가·부문 총량과 견줄 때.
        rule: 국가 통계(IPCC 지침)라 회사 명세서 값과 기준이 다르다 — 비중 계산 시 단위(kt vs t)를 맞춘다. 스냅샷(연 1회 갱신)이며 응답 source 에 날짜가 있다.
        params: find(분야명 부분, 선택), years(최근 몇 년, 기본 5), format(md|json)
        ref: ghg_industry, ghg_emissions
        """
        payload = build_ghg_inventory_payload(find, years)
        return as_pretty_json(payload) if format == "json" else _render(payload)
