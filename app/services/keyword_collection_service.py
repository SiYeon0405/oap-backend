import json
import logging
from datetime import datetime, timezone

from openai import OpenAI

from app.core.config import get_openai_api_key
from app.database.session import get_session
from app.repositories.keyword_repository import KeywordRepository
from app.services.naver_searchad_client import NaverSearchAdClient


logger = logging.getLogger(__name__)
SEED_TYPES = ("PROBLEM", "SOLUTION", "ALTERNATIVE", "RECOMMENDATION", "PRICE", "BRAND")
INDUSTRY_TERMS = {
    "IT/SaaS": "툴", "교육": "학원", "쇼핑몰": "추천", "헬스케어": "병원",
    "뷰티": "샵", "F&B": "맛집", "마케팅": "대행",
}
SYSTEM_PROMPT = "너는 텍스트에서 검색 키워드를 추출하는 도구다. JSON만 출력한다."
USER_PROMPT = """아래 한 줄 설명에서 셋만 추출하라.

한 줄 설명: {한줄설명}
업종: {업종}

[대상] 누구를 위한 서비스인가 (2~4어절)
  좋은 예: 초기 창업자 / 1인 사업자 / 30대 직장인
  나쁜 예: 마케팅이 필요한 모든 분

[문제] 이 서비스가 다루는 분야를 사람들이 검색창에 치는 말로 (2~3어절)
  좋은 예: 스타트업 마케팅 / 온라인 광고 / 인테리어 견적 / 다이어트 식단
  나쁜 예: 서비스 확인 필요 / 마케팅 검증 / 방향성 제시 / 성장 전략 수립
    → 서술어를 명사로 굳힌 표현. 실제로 아무도 검색하지 않는다.
  판단 기준: 이 말을 네이버 검색창에 치는 사람이 하루 한 명이라도 있는가?

[해결수단] 어떻게 해결하는가 (2~3어절)
  좋은 예: 리포트 / 자동 견적 / 1:1 코칭

규칙
- 원문에 없는 내용을 추측해 넣지 말 것
- 알 수 없으면 null
- '검증' '방향성' '솔루션' '최적화' 같은 업계 용어를 그대로 쓰지 말 것.
  일반인이 쓰는 말로 바꿀 것
- 조사·서술어를 붙이지 말 것. 명사구로만

출력 형식
{{"대상":"...","문제":"...","해결수단":"..."}}"""


def normalize_keyword(value: str) -> str:
    return "".join(value.split())


def parse_count(value: int | str) -> int:
    return 5 if value == "< 10" else int(value)


def build_seeds(extracted: dict, service_name: str, industry: str) -> list[tuple[str, str]]:
    problem = extracted.get("문제")
    if not problem:
        logger.warning("Seed extraction did not return a problem keyword")
        return [("BRAND", service_name)]
    solution = INDUSTRY_TERMS.get(industry, "")
    return [
        ("PROBLEM", problem),
        ("SOLUTION", f"{problem} {solution}".strip()),
        ("ALTERNATIVE", f"{problem} 대행사"),
        ("RECOMMENDATION", f"{problem} 추천"),
        ("PRICE", f"{problem} 비용"),
        ("BRAND", service_name),
    ]


class KeywordCollectionService:
    def __init__(self, repository=None, naver_client=None, extractor=None):
        self.repository = repository or KeywordRepository()
        self.naver_client = naver_client or NaverSearchAdClient()
        self.extractor = extractor or self._extract

    @staticmethod
    def _extract(service_name: str, industry: str, one_line_description: str) -> dict:
        response = OpenAI(api_key=get_openai_api_key()).chat.completions.create(
            model="gpt-4o-mini",
            temperature=0,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": USER_PROMPT.format(한줄설명=one_line_description, 업종=industry)},
            ],
        )
        return json.loads(response.choices[0].message.content)

    def collect(self, service_name: str, industry: str, one_line_description: str):
        extracted = self.extractor(service_name, industry, one_line_description)
        seeds = build_seeds(extracted, service_name, industry)
        raw_rows = self.naver_client.fetch_keywords([value for _, value in seeds[:5]])
        raw_rows += self.naver_client.fetch_keywords([seeds[5][1]]) if len(seeds) == 6 else []
        if len(seeds) < 6:
            logger.warning("Seed generation returned only %s seed(s)", len(seeds))

        collected_at = datetime.now(timezone.utc)
        rows_by_keyword = {}
        for row in raw_rows:
            raw_keyword = row.get("relKeyword")
            if not raw_keyword:
                continue
            normalized = normalize_keyword(raw_keyword)
            pc_raw = row.get("monthlyPcQcCnt", 0)
            mobile_raw = row.get("monthlyMobileQcCnt", 0)
            pc_count = parse_count(pc_raw)
            mobile_count = parse_count(mobile_raw)
            rows_by_keyword[normalized] = {
                "keyword": normalized,
                "keyword_raw": raw_keyword,
                "metric": {
                    "pc_count_raw": str(pc_raw),
                    "mobile_count_raw": str(mobile_raw),
                    "pc_count": pc_count,
                    "mobile_count": mobile_count,
                    "total_count": pc_count + mobile_count,
                    "comp_idx": row.get("compIdx"),
                    "source": "naver_searchad_keywordstool",
                    "collected_at": collected_at,
                },
            }
        requested = {normalize_keyword(value) for _, value in seeds}
        if not requested.intersection(rows_by_keyword):
            logger.warning("Naver results did not include a requested seed keyword")
        with get_session() as session:
            return self.repository.add_metrics(session, list(rows_by_keyword.values()))
