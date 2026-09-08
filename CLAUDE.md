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
uv run python scripts/smoke_kind.py                # KIND 원문(지배구조·지속가능)이 아직 읽히는지 (network)
uv run python scripts/refresh_krx_gics.py          # GICS 산업분류 스냅샷 갱신 (월간 워크플로가 대신 함, 키 불필요)
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
  data/krx_gics.json          # GICS 산업분류 KOSPI+KOSDAQ 2,534종목. scripts/refresh_krx_gics.py 로만 갱신
  services/gics.py            # 종목코드 → 경제섹터·산업군 조회, 산업군 필터·집계
  services/        # payload(ToolEnvelope) 를 만드는 도메인 로직
  services/governance_report.py          # 지배구조보고서 원문 파서(세부원칙·서식 표·미준수 사유) — 정규식, lxml 없음
  services/governance_report_payload.py  # 접수번호 고르기 → 원문 → 파서 → scope/find
  services/sustainability_notice.py      # 지속가능경영보고서 자율공시 서식(61979) 파서 — 목차·검증·첨부 PDF 주소
  services/report_text.py                # 첨부 PDF → 페이지 텍스트 캐시 → 검색·발췌 (바이트는 안 남긴다)
  services/ghg_disclosure.py             # 보고서 공시 수치를 **범위 축**(경계·Scope2 방식·NF3)과 함께 집는다
  services/rating_context.py             # 같은 기관 안의 등급 분포 — 세기만 하고 백분위·점수로 바꾸지 않는다
  pdf/extract.py                         # PDF → 텍스트. 훑기 pypdfium2(0.3s/87쪽) · 표 정렬 pdfplumber(0.18s/쪽)
  services/company.py   # 회사 식별 — name_keys(법인격·음차·영문 브랜드·업종어 규칙) 한 곳
  services/aliases.py   # 규칙으로 못 잇는 통칭 사전(「현대차」→ 현대자동차). 값은 포털 약명
  tools/           # public MCP tool facade — 렌더링만 (자동 발견, register_tools)
  resources.py     # oek://tools_guide
tests/fixtures/    # 2026-09-07 실호출 응답 스냅샷
docs/mcp-draft.md  # 설계 초안·로드맵
docs/anecdotes.md  # 실측 노트 — 가정이 틀렸던 지점들. 새 소스를 붙이기 전에 읽는다
```

## Rules

1. **비공식 엔드포인트.** 간격 0.5초, 하루 캐시, User-Agent 명시. 차단은 IP 기준이라 한 머신의 전원이 막힌다.
2. **라이선스는 기관마다 다르다.** (**이 저장소의 코드는 Apache-2.0 이지만 그 라이선스는 등급 데이터에
   미치지 않는다** — 코드를 상업적으로 써도 된다는 것이 등급을 수집·재배포해도 된다는 뜻이 아니다. NOTICE 참고.)
   등급은 각 평가기관 저작물이고 **조건이 서로 다르다**(`codes.AGENCY_LICENSE`,
   2026-09-08 확인): KCGS·MSCI 는 「**내부 용도**로만」, 서스틴베스트·S&P 는 「사전 **서면**허가 없이 어떤 형태의
   복제도 불가」, 한국ESG연구소는 「사전 서면동의 없이 복제·전송·인용·배포 불가」다. **다섯 곳 다 대외 공개는
   안 된다** — 「MSCI 는 용도 제한뿐」은 화면의 한글 요약만 읽은 오독이었다(영문 원문 「for internal use only …
   may not be reproduced or disseminated」). 조건이 다르니 한 기관 조항을 다섯 곳에 붙이지 말고 **값마다 그 기관
   고지와 원문 주소(`AGENCY_NOTICE_URL`)를 붙인다**. 총괄 고지(`LICENSE_NOTICE`)는 포털 상단 문구까지만 담는다.
   조항을 다툴 일이 생기면 요약이 아니라 `notice-box.jsp?type=…` 원문을 본다 — 한글 요약은 영문보다 좁다.
   등급은 **실시간으로만** 가져오고 DB·저장소·로그 어디에도 남기지 않는다(캐시는 메모리뿐). 재배포 금지.
   등급을 **다른 척도로 바꾸지 않는다** — 기관 간 정규화 점수도, 「상위 N%」 백분위도 만들지 않는다.
   「좋은 편인가」는 같은 기관 안에서 **세어서**(이 등급 이상 N사·동점 M사) 답한다. 등급이 6~7단계라
   동점이 30~60%여서 백분위는 지어낸 정밀도다(2025년 실측: 한국ESG연구소 A 등급에 61% 동점).
3. **필드 사전은 `krx/codes.py` 한 곳.** 라벨·슬롯을 다른 파일에 복제하지 않는다.
4. **tool 은 얇게.** 파싱·판정은 services, tool 은 md/json 렌더링만. 도구 설명은 `desc/when/rule/params/ref` 형식.
5. **외부 실패는 degrade, 코드버그는 crash.** `services/safety.py` 의 집합에 없는 예외는 그대로 터뜨린다.
6. **테스트는 network 0.** 새 화면을 붙이면 fixture 를 `tests/fixtures/` 에 스냅샷으로 넣는다.
   다만 **평가기관 등급 값은 합성값으로 바꿔서** 넣는다(`_note` 로 밝힌다) — fixture 가 지켜야 하는 것은 응답
   스키마(슬롯 키·`-` 처리·S&P 숫자화)이지 등급 자체가 아니고, 등급을 저장소에 두면 그 자체가 규칙 2의
   「복제·재배포」다. 서버는 등급을 **실시간으로만** 가져오고 메모리 캐시 밖에 남기지 않는다.
7. **커밋/푸시는 사용자 명시 요청 시만.**
8. **온실가스는 GIR 값 그대로.** GIR 과 보고서는 범위만 맞추면 사실상 같은 값이다(실측 오차 0.001~0.5%) —
   회사가 GIR 에 낸 명세서를 보고서에도 싣기 때문이다. 벌어지면 「값이 다르다」가 아니라 「범위가 다르다」로 답한다
   (경계 · Scope 2 지역/시장기반 · NF3 포함 여부). 보고서에서 수치를 뽑아 필드로 만들지 않는다 — 한 보고서 안에
   값이 여럿이라(SK하이닉스 2024년은 셋) 범위를 잃으면 그 숫자는 틀린 것이나 같다. 명세서(규제 기준, 직접+간접)·인증 배출량·국가 인벤토리(kt)는 기준이 다르므로 한 표에 섞지 않는다. GIR 에 없는 회사는 `no_data` 이지 0 이 아니다. GIR 법인명과 포털·DART 이름은 다르다(「에스케이하이닉스 주식회사」) — 대조는 `services/company.name_keys`(법인격 제거·음차·브랜드 별칭) 한 곳에서만 한다. 통칭(「현대차」)은 `services/aliases.py` 사전에만 넣고, 규칙으로 되는 것은 사전에 넣지 않는다.
9. **DART 명부는 보조다.** 포털에서 못 찾았을 때만 부른다. 키가 없으면 동봉 스냅샷, 실시간이 실패해도 스냅샷으로 내려간다 — 보조 색인이 죽어도 유가증권 조회는 살아야 한다. 스냅샷은 손으로 고치지 않고 `scripts/refresh_listed_companies.py` 로만 갱신한다(정렬·메타가 diff 의 근거). 테스트는 늘 `dart_index` fixture 를 주입한다(이 머신 환경변수에 좌우되지 않게).
10. **포털 목록은 한 해 늦다 — KIND 로 메운다.** 포털의 지속가능경영보고서 목록은 발행년도 선택지가
   전년까지다(2026-09-08 실측: 2025 까지). 같은 날 KIND 에는 2026년 자율공시가 436건 있었다. 빠진 해가
   있을 때만 KIND 공시 검색(`kind.search`)을 **회사·기간당 한 번** 불러 메운다(규칙 1). 호출 모양이 까다롭다 —
   POST **본문** · 종목코드에 **`A` 접두사** · 회사명과 코드를 각각 두 칸에 · `X-Requested-With` 없이.
   어긋나면 오류가 아니라 **안내 페이지**가 와서 「0건」처럼 보이므로 그 문구를 감지해 따로 터뜨린다.
   메운 행은 `source="kind"` 로 표시하고 포털 집계 열(업종·작성기준·검증기관)을 **비운 채 이유를 밝힌다** —
   빈 칸은 「없다」가 아니라 「아직 집계 전」이다. 공시는 6월에 몰리지만 꼬리가 12월까지 가므로 창은 한 해 전체다.
   정정(`[정정]…`)은 드물지만 있다(436건 중 4) — 그 해의 마지막 한 건만 싣고 `amended` 로 밝힌다.
11. **지배구조는 두 층이다.** 포털 집계(`governance_indicators`·`governance_policies`)와 회사 원문(`governance_report`).
   원문 파싱 0건은 「읽지 못함」이지 「0개 준수」가 아니다 — 응답 문구에서 반드시 구분한다. 금융회사는 「지배구조 연차보고서」로
   갈음해 세부원칙이 없다(`no_data`). 서식 표는 `aclass="krx-cg_…"` 인 것만이다 — 자유편집 표는 회사마다 열이 달라 싣지 않는다.
   접수번호는 KIND 번호다. DART 뷰어(`rcpNo=`)에 넣으면 다른 회사 공시가 열린다(실측 2026-09-07) — DART 링크를 만들지 않는다.
12. **PDF 는 두 엔진, 바이트는 안 남긴다.** 훑기는 pypdfium2(87쪽 0.3초), 표 정렬은 pdfplumber(0.18초/쪽).
   pypdf 는 숫자를 깨뜨리고(`567 ,056` 56건) PyMuPDF 는 AGPL 이라 안 쓴다. 캐시에 남기는 것은 **페이지 텍스트뿐**이고
   원본 바이트(4~80MB)는 버린다 — 「찾기→그 쪽 보기」를 위해 25MB 이하 한 건만 10분 들고 있는다.
   검색은 반드시 공백을 지우고 한다: 원문 자간 때문에 그냥 찾으면 「온실가스배출량」이 0쪽으로 나온다(실제 16쪽).
   표 격자(`table=True`)는 **기본값이 아니다.** 값 보존이 97.4%(정렬 텍스트는 100%)이고 좌우 2단 쪽에서
   숫자가 갈린다 — 격자 칸이 평문 토큰에 없으면 의심 칸으로 표시해 돌려준다. 조용히 틀린 값을 주지 않는다.
13. **업종 체계가 셋이고 섞지 않는다.** GICS 산업군 25개(`services/gics.py`, 동봉 스냅샷) · 포털 업종 21개
   (`codes.UPJONG_CODES`) · GIR 지정업종은 서로 다른 분류다 — 삼성전자는 각각 「하드웨어및IT장비」·「전기·전자」·
   「반도체 제조업」이다. GICS 는 지수 포털(index.krx.co.kr)에서 OTP·쿠키로 받아야 해서 스냅샷으로 동봉하고
   `scripts/refresh_krx_gics.py` 로만 갱신한다(월간 워크플로 `refresh-krx-gics`, 휴장일이면 최대 7일 거슬러 올라간다). 스냅샷에 없는 종목은 「분류 없음」이지 「상장 아님」이 아니다.

## Out of Scope (현재)

- 보고서 **표의 수치 자동 추출** — 본문 텍스트는 `sustainability_report_text` 가 읽지만, 표 값을 (연도·부문)에
  대응시키지 않는다. 2단 조판에서 두 표가 섞이는 것을 실측했다 — 틀린 숫자를 주느니 납작한 원문을 주고 넘긴다
- 스캔·이미지 PDF — OCR 하지 않는다. 「글자가 없다」를 「내용이 없다」로 답하지 않는다
- 온실가스 Scope 1·2·3 분리 수치 — GIR 는 합산 규제치만 준다. 보고서 원문(Phase 2 후반)에서 읽어야 한다
- 명세서 대상이 아닌 소규모 배출 회사의 배출량 — 공개 소스가 없다
- 코스닥 종목의 보고서·지배구조 화면 — 포털이 유가증권만 싣는다. 코스닥은 회사명→코드(DART 명부)→등급표까지만 된다.
