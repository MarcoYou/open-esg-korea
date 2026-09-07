# open-esg-korea MCP 초안

> 상태: Draft v0.1 (2026-09-07). KRX ESG 포털 실제 엔드포인트를 호출해 확인한 내용 기반.

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
| 지속가능경영보고서 목록 (전체) | `02/02020000/esg02020000` | `sch_yy`, `upjong`, `isu_cd`(선택), `curPage` | **상장사 795개(2025) 전체 등급 스크리닝 가능**, 접수번호(acpt_no) 포함 |
| 지속가능경영보고서 상세 | `02/02030000/esg02030000_01` | `isu_cd`, `fr_work_dt`, `to_work_dt` | 연도별 보고서, 업종, 작성기준, 제3자 검증기관 |
| 기업지배구조보고서 공시 목록 | `02/02040000/esg02040000_01` | `isu_cd`, 기간 | 공시 제목·일시·접수번호 |
| 지배구조 핵심지표 15개 | `POST /contents/02/02040100/ESG02040100.jspx` | `isu_cd`, `sch_yy` | O/X 15개 + 준수율(`obr_rt`) |
| 지배구조 정책 채택 여부 | `POST /contents/02/02040200/ESG02040200.jspx` | `isu_cd`, `sch_yy` | O/X 수십 개 (집중투표제, 전자투표, 스톡옵션 등) |

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

## 4. 도구(tool) 설계 초안

원칙: 도구 하나 = 사람이 화면 하나에서 얻는 답. 회사 식별은 한 번만 한다.

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
| `get_report_document` (Phase 2) | `acpt_no` 또는 회사+연도 | 보고서 원문 텍스트/절 | DART |
| `get_ghg_emissions` (Phase 3) | 회사, 연도 | Scope 1·2, 에너지 | GIR |

## 5. 응답 설계 원칙

**왜**: ESG 등급은 기관마다 스케일이 다르고(S&P는 0~100 점수, MSCI는 AAA~CCC, KCGS는 S~D),
연도가 어긋나면 비교가 무의미하다. 숫자만 던지면 AI가 잘못 비교한다.

1. 모든 값에 `source`, `as_of_year`, `scale` 을 붙인다.
2. `"-"` 는 `null` 로 정규화하고 `coverage: false` 로 이유를 남긴다.
3. 원문이 있으면 `links` 에 KRX 화면 URL + DART 접수번호 URL 을 넣는다.
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

- 언어: Python + FastMCP (mcp-builder 스킬 기준). httpx 비동기, pydantic 스키마.
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
| 0 | 이 문서 + 엔드포인트 프로브 스크립트 | `python scripts/probe_krx.py 005930` 이 JSON 출력 |
| 1 | KRX 도구 8개 (4절 상단), stdio 서버 | Claude Desktop 에서 "삼성전자 ESG 등급" 질의 응답 |
| 2 | DART 연동: 접수번호 → 원문 절 읽기 | 보고서 원문 인용 가능 |
| 3 | GIR 배출량, 기관별 등급 정규화 점수 | 정량 비교 질의 응답 |

## 9. 열린 질문

1. 등급 스케일을 기관 간 비교 가능한 공통 점수로 변환할지, 원값만 줄지 (원값 우선 제안).
2. `screen_companies` 의 전체 목록 캐시가 7절 라이선스와 충돌하는지 (메모리 캐시·비영구로 시작 제안).
3. 코스닥 커버리지: 목록 엔드포인트가 유가증권 중심인지 확인 필요(`market_gubun` 파라미터 실험).
