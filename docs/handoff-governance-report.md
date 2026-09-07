# 핸드오프 — 기업지배구조보고서 원문 읽기 (Phase 2b-1)

> 클라우드 세션(2026-09-07)에서 로컬 세션으로 넘기는 문서. 클라우드 컨테이너는 KIND(kind.krx.co.kr)가 Akamai 403 으로 막혀
> 응답을 볼 수 없다. 사용자 PC 에서는 KIND·DART 뷰어 둘 다 200 확인(2026-09-07). **이 작업은 KIND 에 붙을 수 있는 로컬 세션에서 한다.**

## 1. 목표 (한 문장)

KRX 포털이 주는 접수번호로 KIND 원문을 열어, 기업지배구조보고서의 **세부원칙 28개에 대한 회사 답변**과 **서식 표**를 돌려주는 도구 하나.
「15개 지표가 왜 미준수인가」는 이 본문에만 있다.

## 2. 이미 있는 것 — 만들지 않는다

| 우리 도구 (KRX 화면, 키 없음) | 주는 것 | OPM `corp_gov_report` 의 대응 scope |
|---|---|---|
| `governance_indicators` | 15개 핵심지표 O/X · 준수율 · 회사 비교 | summary, metrics(비고 제외) |
| `governance_policies` | 정책·사실 74개 Y/N | flags(78개) |
| `esg_disclosures` | 제출 이력·정정 · 접수번호(`acpt_no`) | filings, timeline |

없는 것 = OPM 의 `principles`(세부원칙 답변)·`tables`(서식 표 11종)·지표별 **비고**. 이 셋만 새 도구로.

## 3. OPM 이 하는 방식 (참고: `/home/user/marcoyou/open-proxy-mcp` 또는 GitHub MarcoYou/open-proxy-mcp)

- 문서 찾기: OpenDART `list.json`(키) → `pblntf_detail_ty=I001`, 보고서명 「기업지배구조보고서공시」. 「(자율공시)」「[첨부정정]」「[첨부추가]」 제외.
  금융회사는 「금융회사 지배구조 연차보고서」로 갈음 — 본문 600자 안내문 + PDF 첨부라 표 파싱 불가 → 「다른 서식」으로 분류해 링크만.
- 본문: OpenDART `document.xml`(키) → BeautifulSoup 텍스트.
- 파싱 (`services/corp_gov_report.py`):
  - `_parse_principles`: `(세부원칙 X-Y)` 마커 → 원칙 설명 → 「상기 세부원칙에 대한 준수여부를 …」 다음 줄 = 답변. 정규식 하나.
  - `_parse_metrics`: 15개 라벨 앞 25자로 블록을 찾고 O/X 두 개(당기·직전기) + 비고.
  - `services/corp_gov_form.py`: 서식의 번호 체계 사전 — 절 코드 `[NNNNNN]`(예 `201100` = 2장·핵심원칙1·세부원칙1-1), 표 번호 `표 X-Y-Z`,
    표 몸통의 `<table-group aclass="krx-cg_…">` 개념 코드. `aclass` 없는 표는 회사 자유편집이라 서식 표가 아니다.
- **우리와의 차이**: 우리는 키 없이 KIND 원문을 읽는다. KIND 원문은 KRX 서식 원본이므로 절 코드·표 번호가 같을 가능성이 높다 — 확인이 첫 일.

## 4. 순서

1. **캡처**: 삼성전자 2025 보고서 접수번호 `20250530001005` 로
   `https://kind.krx.co.kr/common/disclsviewer.do?method=search&acptno=20250530001005` 를 받는다.
   응답 안의 문서 번호(docNo/viewerNo)를 찾아 본문 URL(`method=searchContents&docNo=…` 로 추정 — 실제 파라미터는 응답에서 확인)을 연다.
   본문 HTML 을 `tests/fixtures/kind_gov_005930_2025.html` 로 저장(크면 절 몇 개만 남긴 subset 도 하나 더).
   비교용 접수번호: 2024 `20240531001446`, 2026 `20260601000268` (`tests/fixtures/disclosures_005930.json`).
   금융회사 1건(예: KB금융)도 받아 「연차보고서 서식」 분기가 맞는지 본다.
2. **클라이언트**: `open_esg_korea/krx/kind.py` — `KindClient(http, min_interval=0.5, cache_ttl=24h)`, `document(acpt_no) -> {"html", "docs": [...]}`.
   `krx/client.py` 와 같은 예의(간격·UA·메모리 캐시). 실패는 `KindClientError` → `services/safety.EXTERNAL_ERRORS` 에 추가.
   주소·파라미터는 `krx/codes.py` 에 상수로(규칙 3).
3. **파서**: `services/governance_report.py` — OPM 의 `_parse_principles`·`_parse_metrics`(비고)·`corp_gov_form.parse_form_tables` 를 옮긴다.
   BeautifulSoup/lxml 의존을 새로 넣을지 결정 — 지금 프로젝트는 `httpx` 뿐. 정규식으로 되면 의존 없이, 표 파싱은 lxml 이 현실적.
4. **도구**: `tools/governance_report.py` — `governance_report(company, scope="principles"|"tables"|"notes", year=None, find="", format)`.
   `find` 로 원칙 번호(「4-4」)나 키워드(「승계」)만 골라 돌려준다. md 는 원칙별 「원칙 → 답변」, tables 는 표 번호별.
   `next_actions` 로 `governance_indicators` 와 서로 가리킨다.
5. **테스트**: fixture 로 network-0. 프로토콜 계약 테스트의 `EXPECTED_TOOLS` 에 추가.
6. **정리**: `services/reports.py` 의 DART 링크(`DART_URL`) 는 **틀렸다** — KIND 접수번호로 DART 뷰어를 열면 다른 회사 공시가 나온다(실측 2026-09-07).
   링크에서 빼거나 「KIND 번호」로만 표기. README 도구 표·CLAUDE.md Structure/Out of Scope·docs/mcp-draft.md 로드맵 갱신.

## 5. 함정

- 접수번호가 정정본이면 본문이 없을 수 있다(OPM: 014). 제출 이력에서 원본을 고른다.
- KOSDAQ 은 자율공시 — 없으면 `no_data`(「미제출」이지 미준수가 아니다).
- 파싱 0건은 「읽지 못함」이지 「0개 준수」가 아니다 — 응답 문구에 반드시 구분(OPM QA 지적 사례).
- 답변이 「-」「해당사항없음」이면 빈 값으로.
- 실서버 스모크는 로컬에서만 가능. 클라우드 세션은 fixture 테스트만 돈다.

## 6. 완료 기준

- `governance_report(company="삼성전자", scope="principles")` 가 세부원칙 28개 답변을 md 로 돌려준다.
- `scope="tables"` 가 서식 표(최소 이사회 출석률 7-2-1·주총 소집공고 1-1-1)를 표로 돌려준다.
- 금융회사는 `no_data` + 「연차보고서 서식」 경고.
- `uv run pytest -q` 초록, network 0. README·CLAUDE.md·mcp-draft 갱신. PR 로 올린다.
