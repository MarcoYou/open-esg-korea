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

## 도구 (7개)

| 도구 | 무엇을 답하나 |
|---|---|
| `company` | 회사명/종목코드 → 포털 종목코드·ISIN. 모든 도구의 입구 |
| `esg_ratings` | KCGS·MSCI·한국ESG연구소·S&P·서스틴베스트 ESG/E/S/G 등급(연도별) + KCGS 3년 추이 |
| `sustainability_reports` | 지속가능경영보고서 목록 — 작성기준(GRI/SASB/TCFD/SDGs)·제3자 검증기관·원문 링크 |
| `governance_indicators` | 기업지배구조 핵심지표 15개 O/X · 준수율 · 회사 비교 |
| `governance_policies` | 지배구조 정책 채택 여부 74개 항목 |
| `esg_disclosures` | 기업지배구조보고서 공시 이력(정정 포함) |
| `esg_screener` | 유가증권 전체(2025: 795사) 등급 스크리너 — 기관별 최소 등급·업종·보고서 유무 |

## 읽을 때 주의

- 기관마다 스케일이 다릅니다(KCGS S~D, MSCI AAA~CCC, S&P 0-100 점수, 서스틴베스트 AA~E). 기관 간 등급을 나란히 비교하지 마세요.
- `-`(null)는 **그 기관이 평가하지 않았다**는 뜻입니다.
- 포털 검색기는 유가증권 상장사만 다룹니다. 코스닥 **회사명** 검색은 DART 고유번호 명부를 보조 색인으로 씁니다 —
  `OPENDART_API_KEY`(무료, [opendart.fss.or.kr](https://opendart.fss.or.kr)) 를 환경변수로 주면 켜지고, 없으면 6자리 종목코드로 직접 조회하면 됩니다.
  어느 쪽이든 코스닥은 등급표만 나오고 보고서·지배구조 화면은 비어 있을 수 있습니다(포털이 유가증권만 싣습니다).
- `company` 응답의 `corp_code`(DART 고유번호)는 형제 서버 open-proxy-mcp 의 도구에 그대로 넘길 수 있습니다.
- 평가정보는 각 기관의 저작물입니다(KCGS: 비상업적 내부 용도). 응답의 `license` 를 유지하세요.

## 문서

- [MCP 초안·로드맵](docs/mcp-draft.md) — 데이터 소스 지도, 엔드포인트 확인 내용, Phase 2·3
- `python scripts/probe_krx.py 005930 2025` — 포털 응답 스키마 점검

## 개발

```bash
uv sync --dev && uv run pytest -q     # network 0
```
