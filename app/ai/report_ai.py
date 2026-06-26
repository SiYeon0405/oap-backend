import json

from openai import OpenAI


REPORT_KEYS = (
    "service_summary",
    "market_analysis",
    "competitor_analysis",
    "target_customer_analysis",
    "marketing_strategy",
    "platform_recommendation",
)


def generate_analysis_report(analysis_request) -> dict[str, dict]:
    try:
        response_text = _request_analysis_report(analysis_request)
        report = json.loads(response_text)
        if _is_valid_report(report):
            return {key: report[key] for key in REPORT_KEYS}
    except Exception:
        pass

    return _generate_fallback_analysis_report(analysis_request)


def _request_analysis_report(analysis_request) -> str:
    service_context = _build_service_context(analysis_request)
    interview_context = _build_interview_context(analysis_request)

    client = OpenAI()
    response = client.responses.create(
        model="gpt-4.1-mini",
        input=[
            {
                "role": "system",
                "content": (
                    "당신은 대한민국 초기 창업자와 소규모 브랜드를 돕는 "
                    "서비스/시장 분석 전문가입니다. "
                    "반드시 대한민국 시장과 국내 경쟁사 기준으로 분석하세요. "
                    "해외 시장이나 해외 기업 중심 분석은 하지 마세요. "
                    "쉬운 표현으로 작성하고, markdown 코드블록 없이 JSON object만 반환하세요."
                ),
            },
            {
                "role": "user",
                "content": (
                    "아래 서비스 정보를 바탕으로 리포트를 생성하세요.\n\n"
                    f"서비스 정보:\n{json.dumps(service_context, ensure_ascii=False)}\n\n"
                    f"인터뷰 메시지:\n{interview_context}\n\n"
                    "반환 JSON의 최상위 key는 반드시 다음 6개만 사용하세요:\n"
                    "- service_summary\n"
                    "- market_analysis\n"
                    "- competitor_analysis\n"
                    "- target_customer_analysis\n"
                    "- marketing_strategy\n"
                    "- platform_recommendation\n\n"
                    "각 key의 value는 반드시 object여야 합니다. "
                    "각 object에는 title, summary, insights, recommendations를 포함하세요. "
                    "insights와 recommendations는 문자열 배열로 작성하세요."
                ),
            },
        ],
    )
    return response.output_text.strip()


def _build_service_context(analysis_request) -> dict[str, str | None]:
    return {
        "service_name": getattr(analysis_request, "service_name", None),
        "one_line_description": getattr(
            analysis_request,
            "one_line_description",
            None,
        ),
        "industry": getattr(analysis_request, "industry", None),
        "main_question": getattr(analysis_request, "main_question", None),
    }


def _build_interview_context(analysis_request) -> str:
    try:
        messages = getattr(analysis_request, "messages", None)
        if messages is None:
            messages = getattr(analysis_request, "interview_messages", None)
        if not messages:
            return "제공된 인터뷰 메시지가 없습니다."

        return "\n".join(
            f"{getattr(message, 'role', 'unknown')}: "
            f"{getattr(message, 'content', '')}"
            for message in messages
        )
    except Exception:
        return "인터뷰 메시지를 사용할 수 없습니다."


def _is_valid_report(report) -> bool:
    if not isinstance(report, dict):
        return False
    return all(isinstance(report.get(key), dict) for key in REPORT_KEYS)


def _generate_fallback_analysis_report(analysis_request) -> dict[str, dict]:
    service_name = getattr(analysis_request, "service_name", None) or "해당 서비스"
    industry = getattr(analysis_request, "industry", None) or "선택한 업종"
    description = (
        getattr(analysis_request, "one_line_description", None)
        or "입력된 서비스 설명"
    )
    main_question = (
        getattr(analysis_request, "main_question", None)
        or "현재 가장 중요한 사업 질문"
    )

    return {
        "service_summary": {
            "title": "서비스 요약",
            "summary": f"{service_name}은(는) {description}을 중심으로 한 서비스입니다.",
            "insights": [
                f"{industry} 시장에서 해결하려는 문제를 더 구체화할 필요가 있습니다.",
                f"초기 검증 질문은 '{main_question}'을 중심으로 잡을 수 있습니다.",
            ],
            "recommendations": [
                "핵심 고객 1개 그룹을 먼저 정하고 반응을 확인하세요.",
                "서비스가 제공하는 가장 직접적인 이점을 한 문장으로 정리하세요.",
            ],
        },
        "market_analysis": {
            "title": "시장 분석",
            "summary": f"국내 {industry} 시장에서 초기 고객의 실제 불편과 지불 의사를 확인해야 합니다.",
            "insights": [
                "초기에는 전체 시장 규모보다 좁은 고객군의 반복 수요가 더 중요합니다.",
                "국내 소비자 행동과 구매 채널을 기준으로 검증하는 것이 적합합니다.",
            ],
            "recommendations": [
                "국내 커뮤니티, 검색 키워드, 리뷰를 통해 반복되는 불편을 수집하세요.",
                "비슷한 국내 서비스의 가격, 메시지, 유입 채널을 비교하세요.",
            ],
        },
        "competitor_analysis": {
            "title": "경쟁사 분석",
            "summary": "국내 직접 경쟁사와 대체재를 함께 비교해 차별화 지점을 찾아야 합니다.",
            "insights": [
                "초기 브랜드는 기능 수보다 명확한 포지셔닝이 더 중요합니다.",
                "고객이 이미 쓰는 국내 대체 수단도 경쟁 범위에 포함해야 합니다.",
            ],
            "recommendations": [
                "국내 경쟁사 3곳의 가격, 주요 메시지, 고객 후기를 정리하세요.",
                "경쟁사가 강하게 말하지 않는 고객 불편을 차별화 포인트로 검토하세요.",
            ],
        },
        "target_customer_analysis": {
            "title": "타깃 고객 분석",
            "summary": "초기에는 가장 절실한 문제를 가진 고객군부터 정의하는 것이 좋습니다.",
            "insights": [
                "넓은 타깃보다 구매 가능성이 높은 작은 고객군이 실행에 유리합니다.",
                "고객의 상황, 불편, 기존 해결 방식이 구체적일수록 메시지가 선명해집니다.",
            ],
            "recommendations": [
                "타깃 고객을 직업, 상황, 문제 강도 기준으로 좁혀보세요.",
                "5명 이상과 짧은 인터뷰를 진행해 실제 표현을 수집하세요.",
            ],
        },
        "marketing_strategy": {
            "title": "마케팅 전략",
            "summary": "초기 마케팅은 큰 캠페인보다 문제 공감과 전환 검증에 집중해야 합니다.",
            "insights": [
                "초기 고객은 브랜드 인지도보다 자신의 문제를 잘 이해한다는 신호에 반응합니다.",
                "콘텐츠, 검색, 커뮤니티 반응을 통해 메시지를 빠르게 검증할 수 있습니다.",
            ],
            "recommendations": [
                "고객 문제를 직접 언급하는 랜딩 문구와 콘텐츠를 먼저 테스트하세요.",
                "전환 목표를 문의, 사전 신청, 상담 신청 중 하나로 단순화하세요.",
            ],
        },
        "platform_recommendation": {
            "title": "플랫폼 추천",
            "summary": "국내 고객이 이미 정보를 찾고 비교하는 채널부터 우선 검토하는 것이 좋습니다.",
            "insights": [
                "초기에는 운영 부담이 낮고 고객 반응을 바로 볼 수 있는 채널이 적합합니다.",
                "업종에 따라 네이버 검색, 인스타그램, 블로그, 카카오 채널의 우선순위가 달라집니다.",
            ],
            "recommendations": [
                "국내 검색 유입이 중요하면 네이버 블로그와 검색 광고를 검토하세요.",
                "비주얼과 신뢰 형성이 중요하면 인스타그램과 고객 후기 콘텐츠를 활용하세요.",
            ],
        },
    }
