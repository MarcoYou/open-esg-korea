"""public tool 공통 계약 (OPM `services/contracts.py` 의 축소판)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import json
from typing import Any

from open_esg_korea.krx import codes


class AnalysisStatus(str, Enum):
    EXACT = "exact"          # 회사 확정 + 자료 있음
    AMBIGUOUS = "ambiguous"  # 회사 후보 여럿
    NO_DATA = "no_data"      # 회사는 확정됐으나 포털에 해당 자료가 없음 — 실패가 아니라 답
    ERROR = "error"          # 회사 식별 실패 등


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def source_block(page: str, *, provider: str = "KRX ESG 포털", page_url: str | None = None,
                 **extra: Any) -> dict[str, Any]:
    """모든 응답이 싣는 출처. 등급은 「어디서 언제 본 값인가」가 없으면 비교가 불가능하다."""
    return {"provider": provider, "page_url": page_url or codes.PAGE_URLS.get(page, codes.BASE_URL),
            "fetched_at": _utc_now_iso(), **extra}


@dataclass(slots=True)
class ToolEnvelope:
    tool: str
    status: AnalysisStatus | str
    subject: str = ""
    generated_at: str = field(default_factory=_utc_now_iso)
    warnings: list[str] = field(default_factory=list)
    data: dict[str, Any] = field(default_factory=dict)
    source: dict[str, Any] = field(default_factory=dict)
    next_actions: list[str] = field(default_factory=list)
    license: str = codes.LICENSE_NOTICE          # 소스가 다르면(GIR 등) 그 소스의 고지로 바꾼다

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool": self.tool,
            "status": getattr(self.status, "value", self.status),
            "subject": self.subject,
            "generated_at": self.generated_at,
            "warnings": list(self.warnings),
            "data": self.data,
            "source": self.source,
            "license": self.license,
            "next_actions": self.next_actions,
        }


def as_pretty_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)


def clean(value: Any) -> str | None:
    """포털의 빈 값 표기(`-`, 빈 문자열)를 None 으로. 값이 있으면 공백만 정리."""
    if value is None:
        return None
    s = str(value).strip()
    return None if s in ("", "-") else s
