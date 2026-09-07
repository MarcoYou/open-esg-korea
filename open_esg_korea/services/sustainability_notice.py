"""지속가능경영보고서 자율공시 서식(KIND 61979) 파서 — 목록이 못 주는 것을 원문에서 읽는다.

포털 목록(`sustainability_reports`)이 주는 것은 연도·작성기준 아이콘·검증기관뿐이다. 자율공시 본문에는
**보고 대상 기간·보고서 목차·회사 지속가능경영 사이트 주소·작성기준 서술**이 있고, 첨부에는 **PDF 본체**가 있다.

지배구조보고서와 달리 이 서식은 xforms 표 하나다 — 왼쪽 칸이 「1. 보고서 명칭」 식의 항목명, 오른쪽이 값.
삼성전자·현대차·SK·SK하이닉스 4사에서 항목 8개가 같았다(실측 2026-09-07).

PDF 본문은 읽지 않는다(로드맵 2b-2b). 여기서는 **주소만** 준다 — 4MB 안팎이고 표가 많아 텍스트 추출은
따로 검증할 일이다.
"""

from __future__ import annotations

import html as htmllib
import re
from typing import Any
from urllib.parse import urljoin

_TAG_RE = re.compile(r"<[^>]+>")
_BR_RE = re.compile(r"(?i)<br[^>]*>")
_ROW_RE = re.compile(r"(?s)<tr[^>]*>(.*?)</tr>")
_CELL_RE = re.compile(r"(?s)<td[^>]*>(.*?)</td>")
_LABEL_RE = re.compile(r"^\s*(\d+)\.\s*(.+?)\s*$")
_URL_RE = re.compile(r"https?://[^\s()<>\"']+")
_LINK_RE = re.compile(r'(?s)<a\s[^>]*href="([^"]+)"[^>]*>(.*?)</a>')

#: 서식 항목명 → 우리 키. 항목 번호가 아니라 **이름**으로 잇는다(서식이 항목을 끼워 넣어도 덜 깨진다).
FIELDS = {
    "보고서 명칭": "report_title",
    "검증기관": "verifier",
    "작성기준": "standards_text",
    "제출처": "published_at",
    "주요내용": "summary",
    "제출(확인)일자": "confirmed_at",
    "기타 투자판단과 관련한 중요사항": "notes",
}
#: 값이 「-」뿐이면 빈 값이다(서식이 비워 둔 자리).
_EMPTY = {"", "-", "－"}


def _text(fragment: str, *, keep_lines: bool = False) -> str:
    """`<br>` 은 줄바꿈으로 살린다 — 목차·주소가 줄 단위로 적혀 있다."""
    body = _BR_RE.sub("\n", fragment)
    body = htmllib.unescape(_TAG_RE.sub(" ", body)).replace("\xa0", " ")
    if not keep_lines:
        return " ".join(body.split())
    lines = [" ".join(line.split()) for line in body.split("\n")]
    return "\n".join(line for line in lines if line)


def parse_notice(html: str) -> dict[str, Any]:
    """자율공시 본문 → 항목 dict. 못 읽은 항목은 넣지 않는다(빈 문자열로 있는 척하지 않는다)."""
    out: dict[str, Any] = {}
    for row in _ROW_RE.findall(html):
        cells = _CELL_RE.findall(row)
        if len(cells) < 2:
            continue
        label = _text(cells[0])
        m = _LABEL_RE.match(label)
        key = FIELDS.get(m.group(2) if m else label)
        if not key:
            continue
        value = _text(cells[1], keep_lines=True)
        if value in _EMPTY:
            continue
        out[key] = value
        # 검증기관 행만 「국문 | 영문 | 영문명」 4칸이다.
        if key == "verifier" and len(cells) >= 4:
            en = _text(cells[3])
            if en not in _EMPTY:
                out["verifier_en"] = en
    # 제출처 안의 회사 사이트 주소를 따로 뽑아 둔다 — 「원문 어디서 보나」의 답이다.
    site = _URL_RE.search(out.get("published_at", ""))
    if site:
        out["publisher_url"] = site.group(0).rstrip(").,")
    return out


def parse_attachments(html: str, base_url: str) -> list[dict[str, str]]:
    """첨부 문서 화면 → [{name, url}]. 보고서 PDF 본체가 여기 상대 링크로 걸려 있다."""
    items: list[dict[str, str]] = []
    for href, label in _LINK_RE.findall(html):
        name = _text(label).strip("[] ")
        # 파일명에 공백이 그대로 들어 있다(「삼성전자 지속가능…pdf」) — 나머지는 이미 퍼센트 인코딩이라 공백만 고친다.
        items.append({"name": name or href.rsplit("/", 1)[-1],
                      "url": urljoin(base_url, href.replace(" ", "%20"))})
    return items
