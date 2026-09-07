# open-esg-korea

한국 상장사 ESG 정보를 MCP 로 제공하는 Python 서버. 1차 소스는 KRX ESG 포털(esg.krx.co.kr), 보조 소스는 DART 상장사 명부(코스닥 회사명 색인 — 동봉 스냅샷, 키 있으면 실시간).
형제 프로젝트 [open-proxy-mcp](https://github.com/MarcoYou/open-proxy-mcp)(DART 공시) 의 골격을 따른다.

## Purpose

**게이트웨이**다 — 등급을 저장·가공해 다시 파는 것이 아니라, 흩어진 화면을 AI 가 바로 읽을 수 있는 모양으로 넘긴다.
- 값마다 출처(`source`)·연도·스케일을 붙인다. 기관 간 등급을 한 줄에 놓고 비교하지 않는다.
- `-` 는 「미평가」다. 0 이나 나쁜 등급으로 바꾸지 않는다. 자료가 없으면 `status=no_data` 로 말한다.
- 사용자 조회 결과를 저장하지 않는다. 캐시는 메모리에만(프로세스와 함께 사라진다).

## Commands

```bash
uv sync --dev
uv run pytest -q                                   # network 0 (httpx.MockTransport + fixtures)
uv run python -m open_esg_korea                    # streamable-http :8000 → /mcp, /health
uv run python -m open_esg_korea --transport stdio  # Claude Desktop 로컬 연결용
python3 scripts/probe_krx.py 005930 2025           # 포털 응답 스키마가 바뀌었는지 (network)
OPENDART_API_KEY=… uv run python scripts/refresh_listed_companies.py   # 상장사 명부 스냅샷 갱신 (월간 워크플로가 대신 함)
```

## Structure

```
open_esg_korea/
  server.py        # build_mcp() / build_app() / main()
  krx/codes.py     # 화면 code · 기관 슬롯 · 지표/정책 라벨 사전 — 한 벌만
  krx/client.py    # POST 하나(ESG99000001.jspx) + 간격 0.5s + 24h 메모리 캐시
  dart/corp_codes.py # 상장사 명부 3겹: 실시간(키, 7일 메모리 캐시) → data/listed_companies.json 스냅샷 → 없음
  data/listed_companies.json  # OpenDART corpCode.xml 상장사 ~3,900행 스냅샷. scripts/refresh_listed_companies.py 로만 갱신
  services/        # payload(ToolEnvelope) 를 만드는 도메인 로직
  tools/           # public MCP tool facade — 렌더링만 (자동 발견, register_tools)
  resources.py     # oek://tools_guide
tests/fixtures/    # 2026-09-07 실호출 응답 스냅샷
docs/mcp-draft.md  # 설계 초안·로드맵
```

## Rules

1. **비공식 엔드포인트.** 간격 0.5초, 하루 캐시, User-Agent 명시. 차단은 IP 기준이라 한 머신의 전원이 막힌다.
2. **라이선스.** 등급은 각 평가기관 저작물(KCGS: 비상업적 내부 용도). DB 적재·재배포 금지. 모든 응답에 `license` 동봉.
3. **필드 사전은 `krx/codes.py` 한 곳.** 라벨·슬롯을 다른 파일에 복제하지 않는다.
4. **tool 은 얇게.** 파싱·판정은 services, tool 은 md/json 렌더링만. 도구 설명은 `desc/when/rule/params/ref` 형식.
5. **외부 실패는 degrade, 코드버그는 crash.** `services/safety.py` 의 집합에 없는 예외는 그대로 터뜨린다.
6. **테스트는 network 0.** 새 화면을 붙이면 fixture 를 `tests/fixtures/` 에 스냅샷으로 넣는다.
7. **커밋/푸시는 사용자 명시 요청 시만.**
8. **DART 명부는 보조다.** 포털에서 못 찾았을 때만 부른다. 키가 없으면 동봉 스냅샷, 실시간이 실패해도 스냅샷으로 내려간다 — 보조 색인이 죽어도 유가증권 조회는 살아야 한다. 스냅샷은 손으로 고치지 않고 `scripts/refresh_listed_companies.py` 로만 갱신한다(정렬·메타가 diff 의 근거). 테스트는 늘 `dart_index` fixture 를 주입한다(이 머신 환경변수에 좌우되지 않게).

## Out of Scope (현재)

- 보고서 원문 본문(PDF·DART 절 읽기) — Phase 2 후반
- 온실가스 배출량 등 정량 수치 — Phase 3
- 코스닥 종목의 보고서·지배구조 화면 — 포털이 유가증권만 싣는다. 코스닥은 회사명→코드(DART 명부)→등급표까지만 된다.
