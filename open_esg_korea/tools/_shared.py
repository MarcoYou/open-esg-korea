"""md 렌더링 공용 조각."""

from __future__ import annotations

from typing import Any


def head(title: str, payload: dict[str, Any]) -> list[str]:
    lines = [f"# {title}", ""]
    if payload.get("warnings"):
        lines.append("## 유의사항")
        lines.extend(f"- {w}" for w in payload["warnings"])
        lines.append("")
    return lines


def candidates_table(payload: dict[str, Any], tool: str) -> str:
    data = payload.get("data", {})
    cands = data.get("candidates") or []
    lines = head(f"{tool}: {data.get('query', payload.get('subject', ''))}", payload)
    if payload.get("status") == "ambiguous":
        lines.append("회사 후보가 여러 개입니다. 종목코드로 다시 물어보세요.")
    elif not cands:
        return "\n".join(lines)
    else:
        lines.append("혹시 이 회사인가요?")
    lines += ["", "| 회사명 | 종목코드 |", "|---|---|"]
    lines += [f"| {c.get('name', '')} | `{c.get('isu_cd', '')}` |" for c in cands]
    return "\n".join(lines)


def footer(payload: dict[str, Any]) -> list[str]:
    src = payload.get("source", {})
    lines = ["", f"- 출처: {src.get('provider', '')} {src.get('page_url', '')} (조회 {src.get('fetched_at', '')})",
             f"- 라이선스: {payload.get('license', '')}"]
    if payload.get("next_actions"):
        lines.append("- 다음: " + " · ".join(payload["next_actions"]))
    return lines


def ox(v: bool | None, neutral: bool = False) -> str:
    if v is None:
        return "—"
    if neutral:
        return "O" if v else "X"
    return "✅ O" if v else "❌ X"


def dash(v: Any) -> str:
    return "-" if v in (None, "") else str(v)
