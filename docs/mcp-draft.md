# open-esg-korea MCP 초안

> 상태: v0.2 (2026-09-07). Phase 1(KRX 도구 7개, MCP 서버) 구현 완료. 구조는 [open-proxy-mcp](https://github.com/MarcoYou/open-proxy-mcp) 를 따른다.
>
> 실행·구조·규칙은 `CLAUDE.md`, 도구 목록은 `README.md` 가 정본이다. 이 문서는 **설계 판단과 확인 사실**을 남긴다.

## 1. 한 줄 목표

"삼성전자 ESG 등급 어때?" 라고 AI에게 물으면, 5개 평가기관 등급·보고서·지배구조 지표를
**출처와 연도가 붙은 상태로** 바로 답하게 만드는 게이트웨이.

## 2. 왜 MCP인가 (개념)

- **문제**: 한국 상장사 ESG 정보는 KRX ESG 포털, DART, KIND, 평가기관 사이트에 흩어져 있고
  전부 "사람이 클릭하는 화면" 형태다. AI가 직접 쓰기엔 검색 → 팝업 → 표 읽기 과정이 필요하다.
- **왜 MCP**: MCP 서버 하나가 "회사명 → 코드 → 각 화면의 JSON" 변환을 대신하면,
  어떤 AI 클라이언트(Claude, Cursor 등)든 같은 도구를 꽂아 쓸 수 있다.
  즉 **데이터 소스 N개 × 클라이언트 M개**를 **N + M**으로 줄인다.
- **왜 지금 KRX부터**: 확인 결과 KRX ESG 포털은 로그인 없이 POST 하나로 JSON을 준다.
  스크래핑(HTML 파싱)이 아니라 사실상 비공식 API라서 가장 싸게 시작할 수 있다.

## 3. 데이터 소스 지도

### 3-1. KRX ESG 포털 (1차 목표, 확인 완료)

모든 화면이 `POST https://esg.krx.co.kr/contents/99/ESG99000001.jspx` 하나로 통한다.
`code` 파라미터가 "어느 표를 달라"는 뜻이고, 나머지는 검색 조건이다.

| 화면 | code / 경로 | 주요 입력 | 응답 요약 |
|---|---|---|---|
| 기업 ESG 조회 · 등급표 | `02/02010000/esg02010000_01` | `isu_cd`, `sch_yy` | KCGS·MSCI·한국ESG연구소·S&P·서스틴베스트 5개 기관의 ESG/E/S/G 등급, KCGS 첨부 PDF명 |
| 기업 ESG 조회 · 3년 추이 | `02/02010000/esg02010000_09` | `isu_cd` | 연도별 KCGS 등급 + 매출·영업이익 |
| 기업 ESG 조회 · 보고서 요약 | `02/02010000/esg02010000_04` | `isu_cd` | 지속가능경영보고서 건수, GRI/SASB/TCFD/SDGs 채택, 검증기관 |
| 기업 ESG 조회 · 종목 정보 | `02/02010000/esg02010000_05` | `isu_cd` | 발행인코드, ISIN, 약명 |
| 지속가능경영보고서 목록 (전체) | `02/02020000/esg02020000` | `sch_yy`(필수), `upjong`(코드, 예 3015), `pageSize=1000`, `curPage` | **유가증권 795사(2025) 전체 등급 한 번에** — 스크리너 모집단. 접수번호(acpt_no) 포함. `sch_yy` 없으면 빈 결과 |
| 지속가능경영보고서 상세 | `02/02030000/esg02030000_01` | `isu_cd`, `fr_work_dt`, `to_work_dt` | 연도별 보고서, 업종, 작성기준, 제3자 검증기관 |
| 기업지배구조보고서 공시 목록 | `02/02040000/esg02040000_01` | `isu_cd`, 기간 | 공시 제목·일시·접수번호 |
| 지배구조 핵심지표 15개 | `POST /contents/02/02040100/ESG02040100.jspx` | `isu_cd`, `sch_yy` | O/X 15개 + 준수율(`obr_rt`) |
| 지배구조 정책 채택 여부 | `POST /contents/02/02040200/ESG02040200.jspx` | `isu_cd`, `sch_yy` | O/X 74개 (집중투표제, 전자투표, 스톡옵션 등) |
| 회사명 검색기 | `POST …/ESG99000001.jspx?code=/COM/finder_esg_company` | `searchText`(빈 값이면 전체) | **유가증권 834사** 코드·약명 — 회사 색인으로 쓴다 |
| 자동완성 | `POST /contents/02/02030200/suggestionMarket.jspx` | `sch_com_nm` | 검색기와 같은 범위 |

응답 예 (삼성전자, 2025, `esg02010000_01`):

```json
{"result":[{"isu_cd":"005930","com_abbrv":"삼성전자",
  "inst_nm1":"KCGS","yy1":"2025","esg_grd1":"A","envron_grd1":"B+","soc_grd1":"A+","govnc_grd1":"B+",
  "inst_nm2":"MSCI","yy2":"2025","esg_grd2":"AA",
  "inst_nm3":"한국ESG연구소","yy3":"2025","esg_grd3":"A+",
  "inst_nm5":"S&P","yy5":"2025","esg_grd5":"43",
  "inst_nm6":"서스틴베스트","yy6":"2025","esg_grd6":"B","envron_grd6":"A","soc_grd6":"B","govnc_grd6":"C"}]}
```

핵심지표 키 → 라벨 (2025 화면 기준):

| 키 | 지표 |
|---|---|
| `CONVCTN_4WEEK` | 주주총회 4주 전 소집공고 |
| `ELEC_VOT_YN` | 전자투표 실시 |
| `CNCNT_HLD` | 주총 집중일 이외 개최 |
| `CASH_DIV_POSBL` | 현금배당 예측가능성 제공 |
| `DIV_POLIC_NOTI` | 배당정책 연 1회 이상 통지 |
| `HGST_MNG_POLICY_OPER` | CEO 승계정책 |
| `RISK_POLICY_OPER` | 내부통제정책 |
| `OUTDIR_BOD_YN` | 사외이사 이사회 의장 |
| `CNCNT_VOT` | 집중투표제 |
| `COM_VAL_LOSS_RESPBL` | 기업가치 훼손 책임자 임원선임 방지 정책 |
| `BOD_SINGL_YN` | 이사회 단일 성(性) 아님 |
| `INDPD_INSIDE_AUDT` | 독립 내부감사부서 |
| `INSIDE_AUDT_PROFS_YN` | 내부감사기구 회계·재무 전문가 |
| `INSIDE_AUDT_EXT_CFRN` | 외부감사인과 분기 1회 이상 회의 |
| `MNG_INFO_AUDT_ACCSS` | 중요정보 접근 절차 |

### 3-2. 2차 소스 (연결 고리)

| 소스 | 왜 필요한가 | 연결 키 |
|---|---|---|
| DART / OpenDART API | KRX가 주는 건 "등급과 목록"이다. **원문**(지속가능경영보고서·지배구조보고서 PDF, 사업보고서 ESG 절)은 DART에 있다 | KRX 응답의 `acpt_no`(접수번호) → DART 문서 URL |
| KIND (상장공시) | KRX 포털의 공시 목록이 KIND에서 온다. 정정 공시 추적 | `acpt_no` |
| 환경부 온실가스종합정보센터(GIR) 명세서 | 등급이 아닌 **실측 수치**(Scope 1·2 배출량, 에너지 사용량). 정량 질문 대응 | 법인명 → 사업자번호 매핑 필요 |
| KCGS 원 사이트 | KRX에는 등급만 있고 평가 근거·이슈 리스트가 없다 | 종목코드 |

### 3-3. 확인된 제약 (Phase 1 구현 중)

- **커버리지는 유가증권(KOSPI)**: 검색기 834사, 연도별 목록 795사. 코스닥 종목(예 에코프로비엠 247540)은 색인에 없지만
  `isu_cd` 를 직접 주면 등급표·3년 추이는 나온다. → `company` 는 6자리 코드를 색인 없이 통과시키고 그 사실을 경고로 남긴다.
- `sch_yy` 를 비우면 등급표는 전부 `-`, 목록은 빈 배열. → 서버가 올해를 넣고, 없으면 전년으로 한 번 물러서며 그 사실을 밝힌다.
- 업종 필터는 이름이 아니라 코드(3015=전기·전자). `krx/codes.py` 의 `UPJONG_CODES` 로 이름→코드 변환.
- 지배구조 정책 화면은 77행이지만 응답 키는 74개(73~75번은 키 없음).
- 접수번호는 KIND 번호다. DART 뷰어(`rcpNo=`)도 거래소 접수번호를 열어 준다(OPM 실측) — 두 링크를 모두 준다.

## 4. 도구(tool) 설계

원칙: 도구 하나 = 사람이 화면 하나에서 얻는 답. 회사 식별은 한 번만 한다.

Phase 1 에서 구현된 이름(OPM 식 짧은 명사)과 초안 이름의 대응: `resolve_company`→`company`, `get_esg_ratings`+`get_esg_rating_history`→`esg_ratings`(추이 포함),
`list_sustainability_reports`→`sustainability_reports`, `get_governance_indicators`→`governance_indicators`, `get_governance_policies`→`governance_policies`,
`list_esg_disclosures`→`esg_disclosures`, `screen_companies`→`esg_screener`.

| 도구 | 입력 | 출력 | 뒷단 |
|---|---|---|---|
| `resolve_company` | 회사명 또는 종목코드 | `isu_cd`, 약명, ISIN, 시장 | 목록 엔드포인트 전체 캐시에서 퍼지 매칭 + `_05` |
| `get_esg_ratings` | 회사, 연도(기본 최신) | 기관별 ESG/E/S/G 등급 + 각 기관 스케일 설명 | `_01` |
| `get_esg_rating_history` | 회사 | 3년 KCGS 등급·매출 추이 | `_09` |
| `list_sustainability_reports` | 회사(선택), 연도, 업종 | 보고서 목록, 작성기준(GRI/SASB/TCFD/SDGs), 검증기관, DART 링크 | `esg02020000`, `esg02030000_01` |
| `get_governance_indicators` | 회사, 연도, 비교회사(선택) | 15개 핵심지표 O/X, 준수율, 비교표 | `ESG02040100.jspx` |
| `get_governance_policies` | 회사, 연도 | 정책 채택 여부 전체 | `ESG02040200.jspx` |
| `list_esg_disclosures` | 회사, 기간 | 지배구조보고서·정정 공시 목록 | `esg02040000_01` |
| `screen_companies` | 등급 조건(예: KCGS ESG ≥ A, MSCI ≥ AA), 업종, 연도 | 조건 충족 종목 목록 | `esg02020000` 전체(795건) 캐시 후 필터 |
| `governance_report` ✅ | 회사, scope(principles/tables/notes), 제출연도, find | 세부원칙 28개 답변·서식 표·미준수 사유 | KIND 공시 원문(키 없음) |
| `get_ghg_emissions` (Phase 3) | 회사, 연도 | Scope 1·2, 에너지 | GIR |

## 5. 응답 설계 원칙

**왜**: ESG 등급은 기관마다 스케일이 다르고(S&P는 0~100 점수, MSCI는 AAA~CCC, KCGS는 S~D),
연도가 어긋나면 비교가 무의미하다. 숫자만 던지면 AI가 잘못 비교한다.

1. 모든 값에 `source`, `as_of_year`, `scale` 을 붙인다.
2. `"-"` 는 `null` 로 정규화하고 `coverage: false` 로 이유를 남긴다.
3. 원문이 있으면 `links` 에 KIND 원문 URL 을 넣는다. **DART 링크는 넣지 않는다** — 접수번호 체계가 달라
   같은 번호로 DART 뷰어를 열면 다른 회사 공시가 나온다(실측 2026-09-07: 삼성전자 `20250530001005` → 에이치솔루션).
4. 평가기관 저작권 문구를 `license` 필드로 항상 동봉한다(아래 7절).

```json
{
  "company": {"isu_cd": "005930", "name": "삼성전자"},
  "year": 2025,
  "ratings": [
    {"agency": "KCGS", "scale": "S/A+/A/B+/B/C/D", "esg": "A", "e": "B+", "s": "A+", "g": "B+"},
    {"agency": "MSCI", "scale": "AAA~CCC", "esg": "AA", "e": null, "s": null, "g": null},
    {"agency": "S&P", "scale": "0-100 score", "esg": 43}
  ],
  "source": {"provider": "KRX ESG Portal", "url": "https://esg.krx.co.kr/contents/02/02010000/ESG02010000.jsp", "fetched_at": "2026-09-07"},
  "license": "평가정보는 각 기관 저작물. 비상업적 내부용도 한정, 재배포 시 기관 사전승낙 필요."
}
```

## 6. 아키텍처 초안

```
AI 클라이언트 ─MCP(stdio | streamable HTTP)─▶ open-esg-korea server
                                              ├─ tools/        (4절의 도구, 얇은 계층)
                                              ├─ sources/krx   (ESG99000001.jspx 클라이언트, code 상수)
                                              ├─ sources/dart  (Phase 2)
                                              ├─ normalize/    (등급 스케일, "-"→null, 키→라벨)
                                              └─ cache/        (연 단위 데이터 → 24h TTL, 전체 목록은 디스크 캐시)
```

- 언어: Python + `mcp` 2.x `MCPServer`(OPM 과 동일). httpx 비동기. 배포 형태도 OPM 과 같게 streamable-http(무상태·JSON 응답·호스트 보호) 기본, stdio 는 로컬용.
- 캐시가 중요한 이유: 등급은 연 1회 갱신인데 `screen_companies` 는 795행을 훑는다.
  전체 목록을 하루 한 번 받아 두면 스크리닝이 로컬 필터로 끝난다.
- 배포: 로컬 stdio 우선 → 이후 Vercel/Cloud Run 에 HTTP 로 공개.

## 7. 법적·운영 주의 (설계 결정에 영향)

- KRX 포털 고지: 평가정보는 **각 기관 저작물**, KCGS는 "비상업적 내부 용도" 한정, 재배포·가공 시 사전승낙.
  → 서버는 **실시간 게이트웨이**로 설계한다. 등급을 우리 DB에 적재·재배포하지 않고, 응답마다 출처와 라이선스를 동봉한다.
  → 공개 호스팅 시 KCGS(esgdata@cgs.or.kr) 등에 활용 범위 문의를 로드맵에 넣는다.
- 비공식 엔드포인트라 필드명이 바뀔 수 있다. `scripts/probe_krx.py` 로 스키마 스냅샷을 주기 점검한다.
- Rate limit: 화면 사용자 수준(초당 1~2회)으로 제한, User-Agent 와 연락처 명시.

## 8. 로드맵

| Phase | 범위 | 완료 기준 |
|---|---|---|
| 0 ✅ | 이 문서 + 엔드포인트 프로브 스크립트 | `python scripts/probe_krx.py 005930` 이 JSON 출력 |
| 1 ✅ | KRX 도구 7개, streamable-http + stdio 서버, network-0 테스트 35개 | `uv run pytest -q` 초록 · 실서버 스모크(삼성전자·에코프로비엠·스크리너) 응답 확인 |
| 2a ✅ | DART 상장사 명부를 보조 색인으로 — 코스닥 **회사명** 검색, `corp_code` 동봉. 동봉 스냅샷(월간 갱신 워크플로) + 키 있으면 실시간 | 「에코프로비엠 ESG 등급」이 **키 없이** 회사명으로 답함 · 테스트 62개 |
| 2b-1 ✅ | 지배구조보고서 **원문** 읽기 — DART(키) 가 아니라 **KIND(키 없음)** 로 방향 전환. 3단 호출 클라이언트(`krx/kind.py`) + 정규식 파서 + `governance_report` 도구 | 「삼성전자가 집중투표제를 왜 안 하나」에 원문 문장으로 답함 · 원칙 28개·서식 표 30~32개 파싱(실측 3개 연도) · 테스트 117개 |
| 2b-2 | 지속가능경영보고서 원문(PDF) — KIND 첨부·회사 사이트 | 보고서 본문 인용 가능 |
| 3 ✅ | GIR 온실가스: 명세서 배출량(회사별, 2011~) · ETRS 할당/인증 · 국가 인벤토리 스냅샷 → 도구 3개 | 「삼성전자 탄소배출량」「철강 업종 순위」「국가 총배출량 추이」 답함 · 키 없음 · 테스트 79개 |
| 4 | 기관별 등급 정규화 점수, Scope 1·2·3(보고서 원문) | 정량 비교 질의 응답 |

### 2b-1 에서 확인한 것 (2026-09-07, 로컬 실호출)

- KIND 원문은 **3단**이다: `disclsviewer.do?method=search&acptno=` (문서번호) → `method=searchContents&docNo=`
  (`parent.setPath(…)` 로 본문 주소만) → `external/…/{서식번호}.htm` (본문). 접수번호 ≠ 문서번호.
- 서식번호가 문서 종류다: `99667` 기업지배구조보고서, `99669` 금융회사 지배구조 연차보고서(본문은 안내문뿐, 내용은 첨부 PDF).
  KRX 공시 목록 제목의 「(연차보고서)」 접미사로 **원문을 받기 전에** 갈라낼 수 있다.
- 본문 구조는 OPM 이 DART 에서 읽던 것과 같다 — `DetailedPrinciple_N-M` div 28개, 절 코드 `[NNNNNN]`,
  서식 표 `<table-group aclass="krx-cg_…">`. 그래서 OPM 의 절 코드·표 개념 사전을 그대로 쓸 수 있다.
- 「왜 미준수인가」는 **핵심지표 표의 비고가 아니라** 각 원칙의 「(1) 미진한 부분 및 그 사유」에 있다
  (삼성전자 3개 연도 모두 비고 15칸이 비어 있고, 사유는 1-4·7-2·8-1 원칙에만 적혀 있다).
- 본문이 5~12MB 다(회사가 엑셀에서 붙여넣은 자유편집 표 때문). lxml 없이 정규식으로 0.1~0.2초에 읽힌다.

## 9. 열린 질문

1. 등급 스케일을 기관 간 비교 가능한 공통 점수로 변환할지, 원값만 줄지 (원값 우선 제안).
2. `screen_companies` 의 전체 목록 캐시가 7절 라이선스와 충돌하는지 (메모리 캐시·비영구로 시작 제안).
3. ~~코스닥 커버리지~~ → 확인: 포털 자체가 유가증권만 색인한다(`market_gubun` 은 무시됨). → Phase 2a 에서 DART corpCode.xml(상장사 3,931행, 2026-09-07) 을 보조 색인으로 붙여 해결.
   키 의존을 없애기 위해 명부를 `data/listed_companies.json`(314KB) 으로 동봉하고, `refresh-listed-companies` 워크플로가 매월 1일 갱신 PR 을 연다. 실시간(키) → 스냅샷 → 없음 순 폴백. 스냅샷이 120일을 넘으면 응답에 경고가 붙는다.
   대안으로 본 KIND `corpList.do` 다운로드는 403(Akamai), data.krx.co.kr `MDCSTAT01901` 은 세션 없이는 `LOGOUT` 이라 채택하지 않았다.
   주의: DART 는 상장폐지 후에도 stock_code 를 남긴다(신한은행 000010) — 포털 종목마스터도 같다. 그래서 「명부에 있다 = 상장 중」이 아니며, 등급표가 비면 `no_data` 로 답한다.
5. Phase 3 소스 확정(2026-09-07): GIR 명세서 화면은 `maxPageItems=2000` 으로 한 해가 HTML 한 장(1,167행, 895KB)에 오고 엑셀과 값이 같다.
   ETRS 는 `csvYn=Y` 로 cp949 CSV — 사전할당량(계획기간별, 연도 열)·인증 배출량(이행연도별; **2024년 CSV 엔 할당량 열이 없어** 사전할당량으로 채운다).
   국가 인벤토리는 공공데이터포털 15049589 CSV(UTF-8 BOM, 162 분야 × 1990~2023) — 업로드마다 atchFileId 가 바뀌어 스냅샷으로 동봉. 한국에너지공단 마이크로데이터 API·에코앤파트너스 DB(유료)는 제외. NGMS(8443) 는 이 환경에서 접속 불가.
4. ~~회사명 별칭(「현대차」→ 현대자동차)~~ → 해결(2026-09-07): 규칙 셋 + 사전 하나. (a) 한글 음차→알파벳을 이름 어디서나(「삼성에스디에스」=삼성SDS, 「케이티앤지」=KT&G), (b) 영문 브랜드(POSCO↔포스코), (c) 업종어만 빠진 질의는 정확 일치(「삼성화재」), (d) 나머지 통칭 50여 개는 `services/aliases.py` 사전. 별칭이 쓰이면 응답 warnings 에 「통칭으로 보고 …로 찾았습니다」를 남긴다.
