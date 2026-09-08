"""KRX ESG 포털 화면 코드·필드 사전 — **한 벌만** 둔다.

포털은 `POST /contents/99/ESG99000001.jspx` 하나에 `code` 로 "어느 표"를 고른다.
여기 값은 2026-09-07 실호출로 확인한 것이다. 필드명이 바뀌면 `scripts/probe_krx.py` 가 먼저 안다.
"""

from __future__ import annotations

BASE_URL = "https://esg.krx.co.kr"
DATA_PATH = "/contents/99/ESG99000001.jspx"

#: 화면 → code. 값이 곧 포털의 화면 식별자다.
CODE_RATINGS = "02/02010000/esg02010000_01"          # 기업 ESG 조회 · 기관별 등급표 (isu_cd, sch_yy)
CODE_RATING_HISTORY = "02/02010000/esg02010000_09"   # 3년 KCGS 등급 + 매출·영업이익 (isu_cd)
CODE_REPORT_SUMMARY = "02/02010000/esg02010000_04"   # 지속가능경영보고서 요약 (isu_cd)
CODE_ISSUE_INFO = "02/02010000/esg02010000_05"       # 종목 정보: 발행인코드·ISIN (isu_cd)
CODE_COMPANY_LIST = "02/02020000/esg02020000"        # 연도별 전체 상장사 등급표 (sch_yy, upjong, pageSize)
CODE_REPORT_LIST = "02/02030000/esg02030000_01"      # 지속가능경영보고서 상세 목록 (isu_cd, fr/to_work_dt)
CODE_GOV_DISCLOSURES = "02/02040000/esg02040000_01"  # 기업지배구조보고서 공시 목록 (isu_cd, fr/to_work_dt)
CODE_FINDER = "/COM/finder_esg_company"              # 회사명 검색기 (searchText) — code 는 쿼리스트링으로

#: 별도 경로(jspx 가 다르다).
PATH_GOV_INDICATORS = "/contents/02/02040100/ESG02040100.jspx"  # 핵심지표 15개 (isu_cd, sch_yy)
PATH_GOV_POLICIES = "/contents/02/02040200/ESG02040200.jspx"    # 정책 채택 여부 74개 (isu_cd, sch_yy)

#: 사람이 보는 화면 URL — 응답의 `source.page_url` 로 싣는다.
PAGE_URLS = {
    "ratings": f"{BASE_URL}/contents/02/02010000/ESG02010000.jsp",
    "company_list": f"{BASE_URL}/contents/02/02020000/ESG02020000.jsp",
    "reports": f"{BASE_URL}/contents/02/02030000/ESG02030000.jsp",
    "gov_disclosures": f"{BASE_URL}/contents/02/02040000/ESG02040000.jsp",
    "gov_indicators": f"{BASE_URL}/contents/02/02040100/ESG02040100.jsp",
    "gov_policies": f"{BASE_URL}/contents/02/02040200/ESG02040200.jsp",
}

#: 등급표의 기관 슬롯. 응답 키가 `inst_nm{n}`·`esg_grd{n}` 식이라 **슬롯 번호가 기관 식별자**다.
#: 4번 슬롯은 응답에 없다(포털이 비워 둔 자리).
RATING_SLOTS: dict[int, dict[str, str]] = {
    1: {"id": "kcgs", "name": "KCGS", "name_ko": "한국ESG기준원",
        "scale": "S / A+ / A / B+ / B / C / D", "kind": "grade"},
    2: {"id": "msci", "name": "MSCI", "name_ko": "MSCI",
        "scale": "AAA / AA / A / BBB / BB / B / CCC", "kind": "grade"},
    3: {"id": "kesg", "name": "한국ESG연구소", "name_ko": "한국ESG연구소",
        "scale": "S / A+ / A / B+ / B / C / D", "kind": "grade"},
    5: {"id": "sp", "name": "S&P", "name_ko": "S&P Global",
        "scale": "0-100 점수 (ESG Score)", "kind": "score"},
    6: {"id": "sustinvest", "name": "서스틴베스트", "name_ko": "서스틴베스트",
        "scale": "AA / A / BB / B / C / D / E", "kind": "grade"},
}

#: 전체 목록(CODE_COMPANY_LIST) 행의 기관별 접두 — 등급표와 **키 체계가 다르다**.
LIST_AGENCY_PREFIX = {"kcgs": "kcgs", "kesg": "kesg", "msci": "msci", "sp": "sp", "sustinvest": "sv"}

#: 등급 서열. 스크리너의 「이상」 비교에만 쓴다 — 기관 간 비교엔 쓰지 않는다(스케일이 다르다).
GRADE_ORDER: dict[str, list[str]] = {
    "kcgs": ["D", "C", "B", "B+", "A", "A+", "S"],
    "kesg": ["D", "C", "B", "B+", "A", "A+", "S"],
    "msci": ["CCC", "B", "BB", "BBB", "A", "AA", "AAA"],
    "sustinvest": ["E", "D", "C", "B", "BB", "A", "AA"],
}

#: 지배구조 핵심지표 15개 — 응답 키 → (번호, 라벨). 포털 화면 순서.
GOV_INDICATORS: dict[str, tuple[int, str]] = {
    "CONVCTN_4WEEK": (1, "주주총회 4주 전에 소집공고 실시"),
    "ELEC_VOT_YN": (2, "전자투표 실시"),
    "CNCNT_HLD": (3, "주주총회의 집중일 이외 개최"),
    "CASH_DIV_POSBL": (4, "현금 배당관련 예측가능성 제공"),
    "DIV_POLIC_NOTI": (5, "배당정책 및 배당실시계획을 연1회 이상 주주에게 통지"),
    "HGST_MNG_POLICY_OPER": (6, "최고경영자 승계정책 마련 및 운영"),
    "RISK_POLICY_OPER": (7, "위험관리 등 내부통제정책 마련 및 운영"),
    "OUTDIR_BOD_YN": (8, "사외이사가 이사회 의장인지 여부"),
    "CNCNT_VOT": (9, "집중투표제 채택"),
    "COM_VAL_LOSS_RESPBL": (10, "기업가치 훼손 또는 주주권익 침해에 책임이 있는 자의 임원 선임을 방지하기 위한 정책 수립 여부"),
    "BOD_SINGL_YN": (11, "이사회 구성원 모두 단일성(性)이 아님"),
    "INDPD_INSIDE_AUDT": (12, "독립적인 내부감사부서(내부감사업무 지원 조직)의 설치"),
    "INSIDE_AUDT_PROFS_YN": (13, "내부감사기구에 회계 또는 재무 전문가 존재 여부"),
    "INSIDE_AUDT_EXT_CFRN": (14, "내부감사기구가 분기별 1회 이상 경영진 참석 없이 외부감사인과 회의 개최"),
    "MNG_INFO_AUDT_ACCSS": (15, "경영 관련 중요정보에 내부감사기구가 접근할 수 있는 절차 마련 여부"),
}

#: 지배구조 관련 정책 채택 등 — 응답 키 → (번호, 라벨). 화면 74행(번호 73~75 는 응답 키가 없다).
#: 🔴 O/X 는 「준수」가 아니라 **사실**을 묻는 항목이 섞여 있다 — 3·4·14·17·18·72 는 X 가 좋은 쪽일 수 있다.
GOV_POLICIES: dict[str, tuple[int, str]] = {
    "SHRHD_PROPS_HPAGE_YN": (1, "주주제안 절차를 안내하고 있는지 여부"),
    "SHRHD_PROPS_REGUL_YN": (2, "주주제안 처리절차와 기준 관련 규정 마련 및 시행 여부"),
    "SHRHD_PROPS_PERFM_YN": (3, "공시대상기간 개시시점부터 보고서 제출시점까지 주주제안 제출 여부"),
    "OPN_ACPT_YN": (4, "공시대상기간 개시시점부터 보고서 제출시점까지 공개서한 접수 여부"),
    "SHRHD_REFND_POLICY_YN": (5, "배당 포함 주주환원정책 수립 여부"),
    "NOTI_YN": (6, "주주환원정책 연1회 통지 여부"),
    "ENG_DATA_SUPLY_YN": (7, "주주환원정책 영문자료 제공 여부"),
    "PROSPCTS_AMEND_YN": (8, "배당절차 개선 관련 정관반영 여부"),
    "PROSPCTS_ENFORCE_YN": (9, "배당예측가능성 제공 여부"),
    "MINSHRHD_EXER_YN": (10, "소액주주 대상 별도행사 개최 여부"),
    "INQ_ACPT_INFO_YN": (11, "주주와의 소통을 위한 문의 창구 안내 여부"),
    "ENG_SITE_OPER_YN": (12, "영문사이트 운영 여부"),
    "FORN_CHRG_DESIGN_YN": (13, "외국인 담당 직원 지정 여부"),
    "NFAITHDISCLS_DESIGN_YN": (14, "공시대상기간 개시시점부터 보고서 제출시점까지 불성실공시법인 지정 여부"),
    "INSIDE_TR_CTRL_ENFORCE_YN": (15, "내부거래 및 자기거래 통제 관련 정책 시행 여부"),
    "POLICY_ENFORCE_YN": (16, "합병, 분할 등 기업의 소유구조 변동 등에 대한 주주보호 정책 마련 여부"),
    "SCHDL_YN": (17, "공시대상 기간 내 합병, 분할 등 기업의 소유구조 변동 내역 존재 여부"),
    "ISU_YN": (18, "전환사채 등 주식으로 전환될 수 있는 자본조달사항 존재 여부"),
    "POLICY_YN": (19, "최고경영자 승계정책 수립 여부"),
    "CANDIDATE_SELCT_YN": (20, "최고경영자 승계를 위한 후보 선정 여부"),
    "CANDIDATE_EDU_YN": (21, "최고경영자 후보군에 대한 교육 실시 여부"),
    "RISK_POLICY_YN": (22, "전사 리스크관리 정책 마련 여부"),
    "MNG_POLICY_YN": (23, "준법경영 정책 마련 여부"),
    "ACNTG_POLICY_YN": (24, "내부회계관리 정책 마련 여부"),
    "DISCLS_POLICY_YN": (25, "공시정보관리 정책 마련 여부"),
    "ESG_ESTB_YN": (26, "ESG 위원회 설치 여부"),
    "OUTDIR_YN": (27, "이사회 의장이 사외이사인지 여부"),
    "OUTDIR_SYS_YN": (28, "선임사외이사 제도 시행 여부"),
    "EXEC_SYS_YN": (29, "집행임원 제도 시행 여부"),
    "COMITE_SEX_SPECL_YN": (30, "이사회 성별구성 특례 적용기업인지 여부"),
    "COMITE_SAME_SEX_YN": (31, "이사회 구성원이 모두 동성이 아닌지 여부"),
    "RECMND_COMITE_ESTB_YN": (32, "사내·사외이사 선임을 위한 이사후보추천위원회 등 관련 기구 설치 여부"),
    "ACTIV_DTL_SUPLY_YN": (33, "재선임 이사에 대한 과거 이사회 활동내역 제공 여부"),
    "CUMLVOTE_ADOPS_YN": (34, "집중투표제 채택 여부"),
    "CHRG_ELCT_PRVMSR_YN": (35, "부적격 임원 선임을 방지하기 위한 정책 수립 여부"),
    "PROCS_REGUL_ENFORCE_YN": (36, "기업과 사외이사간의 거래 내역을 기업이 확인하는 절차·규정이 있는지 여부"),
    "OUTDIR_MISC_COM_PERMI_YN": (37, "사외이사의 타기업 겸직 허용 관련 내부기준 마련 여부"),
    "EXCHARG_MNPWR_APPL_YN": (38, "사외이사의 정보제공 요구에 대응하기 위한 전담인력 배치 여부"),
    "EDU_EXEC_YN": (39, "사외이사의 업무수행에 필요한 교육 실시 여부"),
    "OUTDIR_MISC_CFRN_YN": (40, "공시대상기간 개시시점부터 보고서 제출시점까지 사외이사 별도회의 개최 여부"),
    "OUTDIR_INDVDL_VALU_YN": (41, "사외이사 개별평가 실시 여부"),
    "REELCT_APPL_YN": (42, "사외이사 평가를 재선임시 반영 여부"),
    "OUTDIR_POLICY_YN": (43, "사외이사 보수 정책 수립 여부"),
    "STKOPT_GRNT_YN": (44, "사외이사에게 스톡옵션 부여 여부"),
    "OTCM_LNK_YN": (45, "사외이사에게 부여된 스톡옵션 행사 조건이 성과와 연동되었는지 여부"),
    "REGUL_BOD_HLD_YN": (46, "정기이사회 개최 여부"),
    "BOD_OPER_REGUL_EXST_YN": (47, "이사회 운영 관련 규정 존재 여부"),
    "EXEC_POLICY_YN": (48, "임원보수정책 수립 여부"),
    "POLICY_OPN_YN": (49, "임원보수정책 공개 여부"),
    "EXEC_REPA_REG_YN": (50, "임원배상책임보험 가입 여부"),
    "INTRPRSN_YN": (51, "기업의 지속가능한 성장을 위해 의사결정시 이해관계자 이익을 고려하는지 여부"),
    "BOD_MTBK_SAVE_YN": (52, "이사회 의사록, 녹취록 보존 여부 및 관련 규정 존재 여부"),
    "BOD_CFRN_CONTN_REC_YN": (53, "이사회 내 주요 토의 내용과 결의 사항을 개별 이사별로 기록하는지 여부"),
    "ACTIV_CONTN_OPN_YN": (54, "정기공시 외 개별이사의 활동 내용 공개 여부"),
    "OUTDIR_OVR_ELCT_ENFORCE_YN": (55, "모든 이사회내 위원회가 사외이사를 과반수 이상 선임하였는지 여부"),
    "AUDTCOMITE_OUTDIR_ELCT_YN": (56, "감사위원회 및 보수위원회를 전원 사외이사로 선임하였는지 여부"),
    "REGUL_YN": (57, "이사회 내 위원회의 조직 및 운영 관련 규정이 있는지 여부"),
    "RPT_YN": (58, "이사회 내 위원회의 결의사항이 이사회에 보고되는지 여부"),
    "AUDTCOMITE_ESTB_YN": (59, "감사위원회 설치 여부"),
    "ACNTG_PROFS_EXST_YN": (60, "내부감사기구 내 회계 또는 재무전문가 존재 여부"),
    "INSIDE_AUDT_REGUL_YN": (61, "내부감사기구 운영 관련 규정 존재 여부"),
    "AUDT_EDU_SUPLY_YN": (62, "내부감사기구에 대한 교육 제공 여부"),
    "EXT_ADVCE_APPL_YN": (63, "내부감사기구에 대한 외부 전문가 자문 지원 여부"),
    "EXAM_PROCS_REGUL_YN": (64, "경영진의 부정행위에 대한 내부감사기구의 조사절차 규정 마련 여부"),
    "ACCSS_PROCS_HD_YN": (65, "기업 경영 정보에 대한 내부감사기구의 정보 접근절차 보유 여부"),
    "APPL_ORG_ESTB_YN": (66, "내부감사기구 지원조직 설치 여부"),
    "APPL_ORG_INDPD_YN": (67, "내부감사기구 지원조직의 독립성 확보 여부"),
    "INDPD_POLICY_YN": (68, "감사위원 및 감사에 대한 독립적인 보수정책 수립 여부"),
    "REGUL_CFRN_HLD_YN": (69, "공시대상기간 개시시점부터 보고서 제출시점까지 내부감사기구의 정기회의 개최 여부"),
    "REGUL_EXST_YN": (70, "감사회의록 및 감사 기록의 작성과 보존, 주주총회 보고절차 관련 내부 규정 존재 여부"),
    "POLICY_EXST_YN": (71, "외부감사인의 독립성 및 전문성을 확보하기 위한 선임 관련 정책 마련 여부"),
    "INDPD_LOSS_YN": (72, "외부감사인 독립성 훼손이 우려되는 상황 존재 여부"),
    "ETC_VALUEUP_VOL_DISCLS_YN": (76, "공시대상기간 개시시점부터 보고서 제출시점까지 기업가치 제고 계획 공시 여부"),
    "ETC_VALUEUP_COMMU_YN": (77, "공시대상기간 개시시점부터 보고서 제출시점까지 주주 및 시장참여자와 기업가치 제고 계획 관련 소통 여부"),
}

#: O/X 가 「좋다/나쁘다」가 아니라 사실 여부인 정책 항목(번호). 렌더링에서 ✅/❌ 대신 중립 표기.
GOV_POLICY_FACT_ITEMS = {3, 4, 14, 17, 18, 30, 72}

#: 지속가능경영보고서 목록의 업종 필터 코드(select 옵션 그대로).
UPJONG_CODES: dict[str, str] = {
    "3021": "건설", "3006": "광업", "3013": "금속", "3024": "금융", "3014": "기계·장비",
    "3018": "기타제조", "3005": "농업, 임업 및 어업", "3012": "비금속", "3008": "섬유·의류",
    "3022": "운송·창고", "3017": "운송장비·부품", "3019": "유통", "3007": "음식료·담배",
    "3016": "의료·정밀기기", "3030": "일반서비스", "3020": "전기·가스", "3015": "전기·전자",
    "3011": "제약", "3009": "종이·목재", "3023": "통신", "3010": "화학",
}

#: 포털 **상단 총괄 고지** 요약. 모든 응답의 `license` 로 싣는다 — 등급은 각 기관 저작물이다.
#: 「비상업적 내부 용도」는 여기 넣지 않는다 — 그건 KCGS 한 곳의 조항이지 다섯 기관 공통이 아니다(2026-09-08 확인).
LICENSE_NOTICE = (
    "평가정보는 각 평가기관(KCGS·MSCI·한국ESG연구소·S&P·서스틴베스트)의 저작물로 KRX ESG 포털이 "
    "게시한 것이며 한국거래소의 의견과 무관합니다. 전체 또는 일부를 복제·송신·출판·재배포하거나 "
    "가공할 경우 해당 기관의 사전승낙이 필요합니다. 기관마다 조건이 다르니 값에 붙은 기관별 고지를 "
    "함께 보고, 정확한 등급·방법론은 각 기관 홈페이지를 확인하세요."
)

#: **기관별** 고지. 조건이 서로 다르다 — 한 문장으로 뭉치면 어느 쪽으로든 틀린다(2026-09-08 포털에서 확인).
#: 등급 값마다 이 고지를 붙인다. 「어디서 온 값인가」와 같은 이유로 「무엇이 허용되는가」도 값에 붙어 다녀야 한다.
AGENCY_LICENSE: dict[str, str] = {
    "kcgs": ("비상업적 내부 용도로만 활용할 수 있으며, 상업적 또는 대외 공개 목적으로 활용할 수 없습니다. "
             "사전승낙 없이 복제·송신·출판·재배포하거나 취득한 정보를 임의 가공할 수 없습니다."),
    # 화면의 한글 요약(「단순 참고목적으로만」)은 일부다 — 단독 고지 페이지의 영문 원문이 넓다.
    "msci": ("내부 용도로만(for internal use only) 사용할 수 있으며, 사전 서면 허가 없이 전체 또는 일부를 "
             "복제·전파할 수 없습니다. 기업금융(ESG 채권·대출)·금융상품(인덱스펀드·ELS)·펀드/포트폴리오 운용·"
             "지수 산출 목적의 사용은 별도의 서면 동의가 필요합니다."),
    "kesg": ("한국ESG연구소의 동의 없이 무단으로 복제·전송·인용·출판·배포하거나 기타 영리 목적으로 "
             "이용할 수 없습니다."),
    "sp": ("복제 및 재배포는 관련 당사자의 사전 서면 허가가 필요합니다. 특정 유가증권의 매매 권고가 아니며 "
           "투자 조언으로 해석되어서는 안 되는, 해당 기업에 대한 S&P Global 의 의견입니다."),
    "sustinvest": ("서스틴베스트의 사전 서면동의 없이 복제·전송·출판·배포·방송 및 기타 방법으로 이용하거나 "
                   "제3자에게 배포할 수 없습니다."),
}

#: 기관별 법적고지 **원문** 주소. `AGENCY_LICENSE` 는 이걸 줄인 것이니, 다툼이 생기면 여기를 본다.
#: 한 페이지에 다섯 기관 고지가 다 들어 있고 `type` 은 어느 것을 펼칠지만 고른다. 영문 원문이 화면 한글 요약보다 넓다
#: (MSCI 는 한글로 「단순 참고목적」이라고만 적혀 있지만 원문은 「internal use only · 사전 서면허가 없이 복제·전파 불가」다).
AGENCY_NOTICE_URL = f"{BASE_URL}/templets/mobile/notice-box.jsp?type={{type}}"

#: 기관 id → 고지 페이지의 `type`. 등급표 슬롯 id 와 철자가 다른 곳이 하나 있다(sustinvest → sv).
AGENCY_NOTICE_TYPE = {"kcgs": "kcgs", "kesg": "kesg", "msci": "msci", "sp": "sp", "sustinvest": "sv"}

#: 회사별 등급 화면. `?isu_cd=` 를 붙이면 그 회사 표가 바로 열린다(2026-09-08 확인) — 값 대신 원본을 가리킬 때 쓴다.
#: 연도(`sch_yy`)는 먹지 않는다. 늘 최신 연도로 열린다.
RATINGS_COMPANY_URL = f"{PAGE_URLS['ratings']}?isu_cd={{isu_cd}}"


# ── KIND(kind.krx.co.kr) — 공시 원문 뷰어 ─────────────────────────────────────
# ESG 포털이 주는 접수번호(`acpt_no`)로 원문을 여는 곳. 포털과 같은 거래소지만 호스트·프로토콜이 다르다
# (JSON 이 아니라 HTML, POST 가 아니라 GET). 아래 값은 2026-09-07 실호출로 확인했다.
#
# 3단이다 — 한 번에 본문이 오지 않는다:
#   ① method=search&acptno=…      뷰어 껍데기. <select id="mainDoc"> 에 **문서번호**(접수번호와 다르다)
#   ② method=searchContents&docNo=… 1KB. 본문 주소를 `parent.setPath('…toc.htm','….htm',…)` 로만 알려준다
#   ③ ②가 준 주소               실제 본문 HTML(삼성전자 2025: 5.7MB, UTF-8)
KIND_BASE_URL = "https://kind.krx.co.kr"
KIND_VIEWER_PATH = "/common/disclsviewer.do"

#: 본문 주소 끝의 서식번호 = 문서 종류. 「연차보고서로 갈음」인지 여기서 갈린다.
KIND_FORM_GOV_REPORT = "99667"      # 기업지배구조보고서 (세부원칙 28개 + 서식 표)
KIND_FORM_ANNUAL_REPORT = "99669"   # 금융회사 지배구조 연차보고서 — 본문은 안내문뿐, 내용은 첨부 PDF

KIND_FORM_SUSTAINABILITY_NOTICE = "61979"   # 지속가능경영보고서 등 관련사항(자율공시) — 목차·검증·회사 사이트
KIND_FORM_ATTACHMENT = "99998"              # 기타공개첨부서류 — 보고서 PDF 본체가 여기 링크로 걸린다

#: KRX 공시 목록 제목의 접미사. 서식번호와 **독립된** 두 번째 신호 — 본문을 받기 전에 걸러낼 수 있다.
KIND_ANNUAL_REPORT_MARK = "(연차보고서)"

#: 사람이 보는 원문 뷰어 URL — 응답의 `source.page_url` 로 싣는다.
KIND_VIEWER_URL = f"{KIND_BASE_URL}{KIND_VIEWER_PATH}?method=search&acptno={{acpt_no}}"

# ── KIND 공시 검색 — 포털 목록이 못 따라오는 최신 연도를 메운다 ─────────────────
# 포털의 지속가능경영보고서 목록은 **한 해 늦다**(2026-09-08 실측: 발행년도 선택지가 2025 까지이고
# 날짜 범위를 2026~ 으로 줘도 같은 7건이 온다). 같은 날 KIND 에는 2026년 자율공시가 259건 있었고
# 삼성전자도 그중 하나였다(2026-06-26). 목록만 없을 뿐 원문·첨부는 우리 뷰어 경로로 이미 읽힌다.
#
# **호출 모양이 까다롭다.** 아래 조합이라야 결과가 온다(형제 프로젝트 open-proxy-mcp 의 확인된 형태):
#   · POST **본문**으로 보낸다(쿼리스트링에 실으면 「서비스 이용에 불편을 드려…」 안내 페이지가 온다)
#   · 종목코드에 **`A` 접두사**를 붙이고 `repIsuSrtCd`·`allRepIsuSrtCd` 둘 다 채운다
#   · 회사명도 `searchCorpName`·`oldSearchCorpName` 둘 다 채운다
#   · `X-Requested-With` 를 **넣지 않는다**
# `reportNm` 으로 제목을 좁히면 회사·연도당 **한 번**이면 된다(실측: 삼성전자 2026 → 1행).
KIND_SEARCH_PATH = "/disclosure/details.do"
KIND_SEARCH_PAGE = f"{KIND_BASE_URL}{KIND_SEARCH_PATH}?method=searchDetailsMain"
#: 제목 필터. 서식명이 「지속가능경영보고서 등 관련사항(자율공시)」라 앞머리만으로 충분하다.
#: 정정공시는 제목이 「[정정]지속가능경영보고서…」라 이 필터에 함께 걸린다 — 걸러내지 않고 받아서 고른다.
KIND_SEARCH_SUSTAINABILITY = "지속가능"

#: 공시 시점(2026-09-08 실측, 전체 시장):
#:     2026년 436건 — 6월 344(79%) · 7월 63 · 8월 20 · 9월 2
#:     2025년 408건 — 6월 299(73%) · 7월 55 · 8월 32 · 9~12월 14
#:     2024년 296건 — 6월 181(61%) · 7월 60 · 8월 19 · 9~12월 24
#: 6월에 몰리지만 **꼬리가 12월까지 간다** — 조회 창을 6~7월로 좁히면 늦게 낸 회사를 놓친다. 한 해 전체를 본다.
#: 정정은 드물다(436건 중 4 · 408건 중 1 · 296건 중 1). 있으면 원본과 별개 접수번호로 한 줄 더 온다.

#: 공시 원문의 고지. 평가기관 등급(`LICENSE_NOTICE`)과 권리자가 다르다 — 원문은 회사가 제출하고 거래소가 게시한 것이다.
KIND_LICENSE_NOTICE = (
    "공시 원문(기업지배구조보고서·지속가능경영보고서 등)은 해당 상장법인이 작성·제출하고 "
    "한국거래소 KIND 가 게시한 문서입니다. "
    "인용 시 회사명·보고서명·공시일(접수번호)을 함께 밝히고, 판단은 원문을 직접 확인하세요. "
    "여기 실린 값은 원문에서 기계적으로 옮긴 것이며 요약·가공하지 않았습니다."
)


# ── KRX 지수 포털(index.krx.co.kr) — GICS 산업분류 ────────────────────────────
# ESG 포털·KIND 와 또 다른 호스트다. OTP 토큰을 먼저 받아야 데이터가 나온다
# (`GenerateOTP.jspx` 로 code 를 받아 `IDX99000001.jspx` 에 실어 보낸다). 쿠키도 필요하다.
# 이 주소는 **갱신 스크립트만** 쓴다 — 서버는 동봉 스냅샷(`data/krx_gics.json`)을 읽는다.
GICS_BASE_URL = "https://index.krx.co.kr"
GICS_OTP_PATH = "/contents/COM/GenerateOTP.jspx"
GICS_DATA_PATH = "/contents/IDX/99/IDX99000001.jspx"
GICS_STOCK_PAGE = f"{GICS_BASE_URL}/contents/MKD/03/0303/03030204/MKD03030204.jsp"   # 산업별 종목현황
GICS_SECTOR_PAGE = f"{GICS_BASE_URL}/contents/MKD/03/0303/03030203/MKD03030203.jsp"  # 산업별 현황
GICS_OPTION_BLD = "/IDX/03/0303/03030204/mkd03030204_01"   # 산업군 선택 목록
GICS_STOCK_BLD = "/IDX/03/0303/03030204/mkd03030204_03"    # 산업군 안 종목
GICS_SECTOR_BLD = "/IDX/03/0303/03030203/mkd03030203"      # 산업군별 종목수·시가총액

#: 시장 코드 → 이름.
GICS_MARKETS = {"STK": "KOSPI", "KSQ": "KOSDAQ"}

#: GICS 경제섹터 11개 — 코드 두 자리. 산업군(네 자리)은 데이터에서 그대로 읽는다(25개, 개편될 수 있다).
GICS_SECTORS = {
    "10": "에너지", "15": "소재", "20": "산업재", "25": "자유소비재", "30": "필수소비재",
    "35": "헬스케어", "40": "금융", "45": "정보기술", "50": "커뮤니케이션서비스",
    "55": "유틸리티", "60": "부동산",
}

#: GICS 는 KRX·S&P/MSCI 의 분류다. 포털 업종(`UPJONG_CODES`, 21개)·GIR 지정업종과 **서로 다른 체계**다.
GICS_NOTICE = (
    "GICS 산업분류는 한국거래소가 S&P·MSCI 의 GICS 기준으로 부여한 것입니다. "
    "KRX ESG 포털의 업종 구분(21개)이나 GIR 지정업종과는 다른 체계이므로 한 표에 섞지 마세요."
)
