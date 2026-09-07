# open-esg-korea

한국 상장사 ESG 정보를 MCP 로 제공하는 Python 서버. 소스 셋: KRX ESG 포털(등급·보고서·지배구조), GIR 온실가스종합정보센터(명세서 배출량·배출권거래제·국가 인벤토리), DART 상장사 명부(코스닥 회사명 색인 — 동봉 스냅샷, 키 있으면 실시간).
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
uv run python scripts/smoke_governance_report.py   # KIND 원문이 아직 읽히는지 (network) — 원칙 28개가 아니면 실패
OPENDART_API_KEY=… uv run python scripts/refresh_listed_companies.py   # 상장사 명부 스냅샷 갱신 (월간 워크플로가 대신 함)
python3 scripts/refresh_ghg_inventory.py --url '<포털 15049589 다운로드 URL>'  # 국가 인벤토리 스냅샷 (연 1회, 12월 공표 후)
```

## Structure

```
open_esg_korea/
  server.py        # build_mcp() / build_app() / main()
  krx/codes.py     # 화면 code · 기관 슬롯 · 지표/정책 라벨 사전 — 한 벌만
  krx/client.py    # POST 하나(ESG99000001.jspx) + 간격 0.5s + 24h 메모리 캐시
  krx/kind.py      # KIND 공시 원문 3단(뷰어→경로→본문). 접수번호로 원문 HTML(5~12MB), 키 없음
  gir/codes.py     # GIR·ETRS 화면 주소·계획기간·부문 사전 — 한 벌만
  gir/client.py    # 명세서 HTML(한 해 한 장)·ETRS CSV(cp949) + 간격 0.5s + 24h 메모리 캐시
  dart/corp_codes.py # 상장사 명부 3겹: 실시간(키, 7일 메모리 캐시) → data/listed_companies.json 스냅샷 → 없음
  data/listed_companies.json  # OpenDART corpCode.xml 상장사 ~3,900행 스냅샷. scripts/refresh_listed_companies.py 로만 갱신
  data/ghg_inventory.json     # 국가 온실가스 인벤토리 1990~ (162 분야). scripts/refresh_ghg_inventory.py 로만 갱신
  services/        # payload(ToolEnvelope) 를 만드는 도메인 로직
  services/governance_report.py          # 지배구조보고서 원문 파서(세부원칙·서식 표·미준수 사유) — 정규식, lxml 없음
  services/governance_report_payload.py  # 접수번호 고르기 → 원문 → 파서 → scope/find
  services/company.py   # 회사 식별 — name_keys(법인격·음차·영문 브랜드·업종어 규칙) 한 곳
  services/aliases.py   # 규칙으로 못 잇는 통칭 사전(「현대차」→ 현대자동차). 값은 포털 약명
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
8. **온실가스는 GIR 값 그대로.** 명세서(규제 기준, 직접+간접)·인증 배출량·국가 인벤토리(kt)는 기준이 다르므로 한 표에 섞지 않는다. GIR 에 없는 회사는 `no_data` 이지 0 이 아니다. GIR 법인명과 포털·DART 이름은 다르다(「에스케이하이닉스 주식회사」) — 대조는 `services/company.name_keys`(법인격 제거·음차·브랜드 별칭) 한 곳에서만 한다. 통칭(「현대차」)은 `services/aliases.py` 사전에만 넣고, 규칙으로 되는 것은 사전에 넣지 않는다.
9. **DART 명부는 보조다.** 포털에서 못 찾았을 때만 부른다. 키가 없으면 동봉 스냅샷, 실시간이 실패해도 스냅샷으로 내려간다 — 보조 색인이 죽어도 유가증권 조회는 살아야 한다. 스냅샷은 손으로 고치지 않고 `scripts/refresh_listed_companies.py` 로만 갱신한다(정렬·메타가 diff 의 근거). 테스트는 늘 `dart_index` fixture 를 주입한다(이 머신 환경변수에 좌우되지 않게).
10. **지배구조는 두 층이다.** 포털 집계(`governance_indicators`·`governance_policies`)와 회사 원문(`governance_report`).
   원문 파싱 0건은 「읽지 못함」이지 「0개 준수」가 아니다 — 응답 문구에서 반드시 구분한다. 금융회사는 「지배구조 연차보고서」로
   갈음해 세부원칙이 없다(`no_data`). 서식 표는 `aclass="krx-cg_…"` 인 것만이다 — 자유편집 표는 회사마다 열이 달라 싣지 않는다.
   접수번호는 KIND 번호다. DART 뷰어(`rcpNo=`)에 넣으면 다른 회사 공시가 열린다(실측 2026-09-07) — DART 링크를 만들지 않는다.

## Out of Scope (현재)

- 지속가능경영보고서 원문 본문(PDF) — 지배구조보고서 원문은 `governance_report` 로 읽는다(KIND HTML). PDF 는 아직
- 온실가스 Scope 1·2·3 분리 수치 — GIR 는 합산 규제치만 준다. 보고서 원문(Phase 2 후반)에서 읽어야 한다
- 명세서 대상이 아닌 소규모 배출 회사의 배출량 — 공개 소스가 없다
- 코스닥 종목의 보고서·지배구조 화면 — 포털이 유가증권만 싣는다. 코스닥은 회사명→코드(DART 명부)→등급표까지만 된다.
