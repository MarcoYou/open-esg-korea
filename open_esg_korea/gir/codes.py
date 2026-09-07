"""GIR 화면 주소·파라미터·라벨 사전 — 한 벌만 (KRX 의 `krx/codes.py` 와 같은 역할).

세 화면, 전부 로그인·키 없이 열린다(2026-09-07 실측):
- 명세서 배출량 통계  https://www.gir.go.kr/home/index.do?menuId=37
    배출권거래제·목표관리제 대상 업체(연 1,170개 안팎)의 법인별 온실가스 배출량(tCO₂eq)·에너지 사용량(TJ).
    `maxPageItems=2000` 이면 한 해가 HTML 한 장(~900KB)에 다 온다. 2011~2025.
- ETRS 배출권거래정보  https://etrs.gir.go.kr/home/index.do?menuId=20|24
    인증 배출량(menuId=20, 이행연도별)·사전할당량(menuId=24, 계획기간별) CSV(cp949).
- 국가 온실가스 인벤토리  공공데이터포털 15049589 (CSV, 1990~2023, 연간) → `data/ghg_inventory.json` 스냅샷.
"""

from __future__ import annotations

GIR_BASE_URL = "https://www.gir.go.kr"
ETRS_BASE_URL = "https://etrs.gir.go.kr"

STATEMENT_PATH = "/home/index.do"                          # menuId=37, condition.year, maxPageItems
STATEMENT_MENU = "37"
STATEMENT_PAGE_SIZE = 2000
STATEMENT_FIRST_YEAR = 2011

CERTIFIED_PATH = "/home/infoOpen/infoOpenList9Excel.do"     # menuId=20 — 인증 배출량 CSV
ALLOCATION_PATH = "/home/infoOpen/infoOpenList10Excel.do"   # menuId=24 — 사전할당량 CSV

PAGE_URLS = {
    "statement": f"{GIR_BASE_URL}/home/index.do?menuId=37",
    "certified": f"{ETRS_BASE_URL}/home/index.do?menuId=20",
    "allocation": f"{ETRS_BASE_URL}/home/index.do?menuId=24",
    "inventory": "https://www.data.go.kr/data/15049589/fileData.do",
}

#: 배출권거래제 계획기간 → 이행연도. 4차는 사전할당량만 공개(인증은 2026년 이행분부터).
PLAN_PERIODS: dict[int, tuple[int, ...]] = {
    1: (2015, 2016, 2017),
    2: (2018, 2019, 2020),
    3: (2021, 2022, 2023, 2024, 2025),
    4: (2026, 2027, 2028, 2029, 2030),
}


def plan_period_of(year: int) -> int | None:
    for period, years in PLAN_PERIODS.items():
        if year in years:
            return period
    return None


#: ETRS 부문 코드 (condition.sectCd)
ETS_SECTORS = {"B001": "전환", "B002": "산업", "A021": "건물", "B003": "수송", "A020": "폐기물", "B004": "공공·기타"}

#: 명세서 지정구분
DESIGNATION_KINDS = {"업체": "업체 단위(모든 사업장 합산)", "사업장": "사업장 단위(해당 사업장만)"}

LICENSE_NOTICE = ("온실가스 배출량·에너지 사용량은 기후에너지환경부 온실가스종합정보센터(GIR)가 공개한 명세서·배출권거래제 정보이며 "
                  "공공데이터포털 등록 자료로 이용허락 범위 제한이 없습니다. 값은 업체가 보고하고 제3자가 검증한 규제 기준(직접+간접 배출)이라 "
                  "지속가능경영보고서의 자발적 공시치(Scope 1·2·3 구분)와 다를 수 있습니다. 국가 인벤토리는 IPCC 지침에 따른 국가 통계입니다.")
