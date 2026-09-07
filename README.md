# open-esg-korea

한국 상장사의 ESG 데이터를 더 쉽고 빠르고 AI-friendly 하게 접근하기 위한 게이트웨이 — MCP 서버.

[KRX ESG 포털](https://esg.krx.co.kr)에 흩어진 기관별 ESG 등급·지속가능경영보고서·기업지배구조보고서 지표를
AI 클라이언트(Claude, Cursor 등)가 자연어로 바로 물을 수 있게 합니다.
형제 프로젝트 [open-proxy-mcp](https://github.com/MarcoYou/open-proxy-mcp)(DART 공시 분석)와 같은 구조입니다.

## 빠른 시작

```bash
uv sync
uv run python -m open_esg_korea                     # http://localhost:8000/mcp
uv run python -m open_esg_korea --transport stdio   # Claude Desktop 로컬 연결
```

Claude Desktop `claude_desktop_config.json` 예:

```json
{"mcpServers": {"open-esg-korea": {"command": "uv", "args": ["run", "--directory", "/path/to/open-esg-korea",
  "python", "-m", "open_esg_korea", "--transport", "stdio"]}}}
```

첫 질문: `삼성전자 ESG 등급 알려줘` → 5개 기관 등급표와 3년 추이가 출처·연도와 함께 나오면 연결된 것입니다.

## 도구 (12개)

| 도구 | 무엇을 답하나 |
|---|---|
| `company` | 회사명/종목코드 → 포털 종목코드·ISIN. 모든 도구의 입구 |
| `esg_ratings` | KCGS·MSCI·한국ESG연구소·S&P·서스틴베스트 ESG/E/S/G 등급(연도별) + KCGS 3년 추이 |
| `sustainability_reports` | 지속가능경영보고서 목록 + 최신 한 건의 공시 원문 — 보고 대상 기간·목차·검증기관·회사 공개처·첨부 PDF 주소 |
| `sustainability_report_text` | 지속가능경영보고서 **PDF 본문** — 키워드가 몇 쪽에 있는지·그 대목 발췌·쪽 전체 보기 |
| `governance_indicators` | 기업지배구조 핵심지표 15개 O/X · 준수율 · 회사 비교 |
| `governance_policies` | 지배구조 정책 채택 여부 74개 항목 |
| `governance_report` | 기업지배구조보고서 **원문** — 세부원칙 28개 답변·서식 표·미준수 사유(왜 미준수인지) |
| `esg_disclosures` | 기업지배구조보고서 공시 이력(정정 포함) |
| `esg_screener` | 유가증권 전체(2025: 795사) 등급 스크리너 — 기관별 최소 등급·업종·보고서 유무 |
| `ghg_emissions` | 회사별 온실가스 배출량(GIR 명세서, tCO₂eq·에너지 TJ·검증기관) + 5년 추이 + 배출권거래제 할당 대비 인증 배출량 |
| `ghg_industry` | 지정업종별 배출량 순위 · 업종 안 법인 순위와 비중 (명세서 합산) |
| `ghg_national_inventory` | 국가 온실가스 인벤토리 — 총량·5개 분야·세부 부문(철강·시멘트·도로수송…) 1990~ 시계열 |

## 읽을 때 주의

- 기관마다 스케일이 다릅니다(KCGS S~D, MSCI AAA~CCC, S&P 0-100 점수, 서스틴베스트 AA~E). 기관 간 등급을 나란히 비교하지 마세요.
- `-`(null)는 **그 기관이 평가하지 않았다**는 뜻입니다.
- 포털 검색기는 유가증권 상장사만 다룹니다. 코스닥 **회사명** 검색은 저장소에 동봉한 상장사 명부 스냅샷
  (`open_esg_korea/data/listed_companies.json`, OpenDART 고유번호 명부에서 매월 갱신)으로 종목코드를 찾습니다 — 키 없이 됩니다.
  `OPENDART_API_KEY`(무료, [opendart.fss.or.kr](https://opendart.fss.or.kr)) 를 주면 스냅샷 대신 실시간 명부를 씁니다(그 사이 상장·개명한 회사까지).
  어느 쪽이든 코스닥은 등급표만 나오고 보고서·지배구조 화면은 비어 있을 수 있습니다(포털이 유가증권만 싣습니다).
- 회사명은 통칭·음차·영문 표기를 알아듣습니다(「현대차」「에스케이하이닉스」「삼성SDS」「케이티앤지」). 별칭이 쓰이면 응답에 그 사실이 적힙니다.
- `company` 응답의 `corp_code`(DART 고유번호)는 형제 서버 open-proxy-mcp 의 도구에 그대로 넘길 수 있습니다.
- 온실가스는 [온실가스종합정보센터(GIR)](https://www.gir.go.kr/home/index.do?menuId=37) 명세서 공개정보입니다 — 배출권거래제·목표관리제
  대상 업체(연 1,170개 안팎)만 있고, 없으면 `no_data` 이지 0 이 아닙니다. 검증된 규제 기준(직접+간접)이라 보고서의 Scope 1·2·3 과 다를 수 있습니다.
  자회사가 따로 지정된 경우(삼성디스플레이·포스코퓨처엠)는 「관련 법인」으로 보여 줍니다. 키 없이 조회됩니다.
- 지배구조는 두 층입니다. `governance_indicators`(15개 O/X)·`governance_policies`(74개 Y/N)는 **KRX 가 집계한 값**이고,
  `governance_report` 는 **회사가 쓴 원문**(KIND)입니다 — 「왜 미준수인가」는 원문에만 있습니다. 원문에서 아무것도 읽지 못하면
  「0개 준수」가 아니라 「읽지 못함」으로 답합니다. 금융회사는 「지배구조 연차보고서」로 갈음해 세부원칙이 없습니다(미제출·미준수가 아닙니다).
- 지속가능경영보고서 PDF 본문은 `sustainability_report_text` 로 읽습니다. **검색은 공백을 무시합니다** —
  원문이 자간을 벌려 조판해 「온실가스 배출량」처럼 띄어져 있어, 그대로 찾으면 있는 내용도 0건이 됩니다.
  못 찾으면 「없다」가 아니라 「이 표기로 못 찾았다」입니다. 이미지로만 된 PDF 는 읽지 못합니다(OCR 하지 않습니다).
- **보고서의 수치를 기계적으로 뽑지 않습니다.** 표는 원문 배치를 편 형태로 돌려주며, 값이 어느 연도·부문인지는
  원문 PDF 로 확인해야 합니다 — 2단 조판 페이지에서 두 표가 섞이는 것을 확인했습니다.
  `table=True` 로 격자를 받을 수도 있지만 **실험적**입니다: 값 보존이 97.4%(정렬 텍스트는 100%)이고,
  쪼개진 것으로 보이는 칸은 `⚠` 로 표시해 돌려줍니다. 의심 칸이 0이 아니면 정렬 텍스트와 대조하세요.
- 공시 목록의 접수번호는 **KIND(거래소) 번호**입니다. DART 접수번호와 체계가 달라, 같은 번호로 DART 뷰어를 열면 다른 회사 공시가 나옵니다.
- 평가정보는 각 기관의 저작물입니다(KCGS: 비상업적 내부 용도). 응답의 `license` 를 유지하세요. 공시 원문은 제출 회사의 문서이므로
  `governance_report` 는 그 고지를 따로 싣습니다.

## 문서

- 국가 인벤토리 스냅샷 갱신(연 1회): `python3 scripts/refresh_ghg_inventory.py --url '<공공데이터포털 15049589 다운로드 URL>'`
- 스냅샷 수동 갱신: `OPENDART_API_KEY=... uv run python scripts/refresh_listed_companies.py` (월간 워크플로 `refresh-listed-companies` 가 같은 일을 하고 PR 을 엽니다 — 저장소 secret `OPENDART_API_KEY` 필요).
- [MCP 초안·로드맵](docs/mcp-draft.md) — 데이터 소스 지도, 엔드포인트 확인 내용, Phase 2·3
- `python scripts/probe_krx.py 005930 2025` — 포털 응답 스키마 점검
- `uv run python scripts/smoke_kind.py` — KIND 공시 원문(지배구조·지속가능)이 아직 읽히는지 점검(실서버)

## 개발

```bash
uv sync --dev && uv run pytest -q     # network 0
```
