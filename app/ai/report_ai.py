import json

from openai import OpenAI

from app.ai.report_retriever import retrieve_report_knowledge


REPORT_KEYS = (
    "service_summary",
    "market_analysis",
    "competitor_analysis",
    "target_customer_analysis",
    "marketing_strategy",
    "platform_recommendation",
)
MAX_MESSAGE_CONTENT_LENGTH = 500
MAX_INTERVIEW_MESSAGES = 20


def generate_analysis_report(
    analysis_request,
    interview_messages=None,
) -> dict[str, dict]:
    try:
        response_text = _request_analysis_report(analysis_request, interview_messages)
        report = json.loads(response_text)
        if _is_valid_report(report):
            return {key: report[key] for key in REPORT_KEYS}
    except Exception:
        pass

    return _generate_fallback_analysis_report(analysis_request)


def _request_analysis_report(analysis_request, interview_messages=None) -> str:
    service_context = _build_service_context(analysis_request)
    user_answer_context = _build_user_answer_context(interview_messages)
    interview_context = _build_interview_context(interview_messages)
    rag_context = retrieve_report_knowledge(
        "\n".join(
            [
                str(service_context.get("service_name") or ""),
                str(service_context.get("one_line_description") or ""),
                str(service_context.get("industry") or ""),
                str(service_context.get("main_question") or ""),
                user_answer_context,
            ]
        )
    )

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
            *(
                [
                    {
                        "role": "user",
                        "content": (
                            "아래 Retrieved Knowledge는 3순위 보조 참고자료입니다. "
                            "사용자 정보가 부족한 경우에만 참고하고, 서비스 기본 정보나 인터뷰 답변과 충돌하면 "
                            "서비스 기본 정보와 인터뷰 답변을 우선하세요.\n\n"
                            f"{rag_context}"
                        ),
                    }
                ]
                if rag_context
                else []
            ),
            {
                "role": "user",
                "content": (
                    "아래 서비스 정보를 바탕으로 리포트를 생성하세요.\n\n"
                    f"서비스 정보:\n{json.dumps(service_context, ensure_ascii=False)}\n\n"
                    f"USER 답변 요약:\n{user_answer_context}\n\n"
                    f"전체 인터뷰 문맥:\n{interview_context}\n\n"
                    "정보 우선순위는 1순위 서비스 기본 정보, 2순위 사용자 인터뷰 답변, "
                    "3순위 Retrieved Knowledge입니다. Retrieved Knowledge는 사용자 정보가 부족할 때만 "
                    "보조 자료로 사용하세요.\n\n"
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
            {
                "role": "user",
                "content": (
                    "추가 작성 기준을 반드시 따르세요.\n\n"
                    "전체 리포트 기준:\n"
                    "- 대한민국 시장 기준으로 작성하세요.\n"
                    "- 초기 창업자와 소규모 브랜드가 실행할 수 있는 수준으로 작성하세요.\n"
                    "- 서비스 기본 정보와 인터뷰 답변을 Retrieved Knowledge보다 우선 근거로 사용하세요.\n"
                    "- 모르는 사실은 단정하지 마세요.\n"
                    "- 실제 회사명과 플랫폼명은 국내에서 널리 알려진 범위에서만 사용하세요.\n"
                    "- 결과는 반드시 JSON object만 반환하고 markdown 코드블록은 사용하지 마세요.\n"
                    "- JSON 최상위 key는 기존 6개만 사용하고, 모든 value는 dict 타입을 유지하세요.\n\n"
                    "competitor_analysis 작성 기준:\n"
                    "- 대한민국 시장 기준으로 분석하세요.\n"
                    "- 가능한 경우 실제 국내 서비스, 플랫폼, 기업명을 2~4개 언급하세요.\n"
                    "- 확실하지 않은 기업명은 단정하지 말고 '유사 경쟁군' 또는 '간접 경쟁 채널'로 표현하세요.\n"
                    "- 해외 기업 중심 분석은 금지하세요.\n"
                    "- 각 경쟁 대상마다 경쟁사/경쟁 채널명, 강점, 약점, 우리 서비스의 차별화 지점, 초기 창업자 관점의 대응 전략을 포함하세요.\n\n"
                    "platform_recommendation 작성 기준:\n"
                    "- 단순히 특정 플랫폼이 좋다는 수준으로 쓰지 말고 추천 우선순위 형태로 작성하세요.\n"
                    "- 업종과 인터뷰 답변에 맞는 국내 사용 가능 플랫폼을 고르세요.\n"
                    "- 예시는 인스타그램 릴스, 네이버 플레이스, 네이버 블로그, 카카오맵, 당근, 유튜브 쇼츠 등입니다.\n"
                    "- 각 플랫폼마다 추천 순위, 추천 이유, 적합한 고객 단계(인지도/관심/전환/재방문), 예산이 적을 때 실행 방법, 기대 효과, 주의할 점을 포함하세요.\n\n"
                    "marketing_strategy 작성 기준:\n"
                    "- 추상적 조언을 피하고 1개월, 2개월, 3개월 실행 계획 형태로 작성하세요.\n"
                    "- 각 월별로 목표, 실행 액션, 사용할 채널, 측정할 KPI, 주의할 리스크를 포함하세요.\n"
                    "- 초기 창업자와 소규모 브랜드가 실행 가능한 수준으로 작성하세요.\n"
                    "- 큰 광고 예산이 필요한 전략은 피하고 저예산 실험 중심으로 작성하세요."
                    "\n\n항목별 추가 품질 기준:\n"
                    "- 모든 분석 항목은 추상적인 조언보다 바로 실행할 수 있는 문장으로 작성하세요.\n"
                    "- market_analysis에는 국내 시장 기준, 고객 수요, 진입 난이도, 성장 가능성을 포함하세요.\n"
                    "- competitor_analysis에는 국내 경쟁사, 대체재, 간접 경쟁 서비스를 함께 포함하세요.\n"
                    "- target_customer_analysis에는 고객 페르소나, 문제 상황, 구매 동기를 구체적으로 작성하세요.\n"
                    "- platform_recommendation에는 추천 플랫폼별 활용 목적과 추천 이유를 명확히 작성하세요.\n"
                    "- marketing_strategy에는 1개월, 2개월, 3개월 실행 로드맵을 포함하세요.\n"
                    "- 초기 창업자와 소규모 브랜드 기준의 저예산 실행 방안을 우선 작성하세요.\n"
                    "- 존재하지 않는 기업명을 단정하지 말고, 확실하지 않으면 '유사 서비스/대체재'로 표현하세요."
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


def _build_user_answer_context(interview_messages) -> str:
    try:
        messages = _sort_interview_messages(interview_messages)
        user_messages = [
            message
            for message in messages
            if _is_user_message(message)
        ]
        if not user_messages:
            return "제공된 USER 답변이 없습니다."

        return "\n".join(
            f"- {_truncate_message_content(getattr(message, 'content', ''))}"
            for message in user_messages[:MAX_INTERVIEW_MESSAGES]
        )
    except Exception:
        return "USER 답변을 사용할 수 없습니다."


def _build_interview_context(interview_messages) -> str:
    try:
        messages = _sort_interview_messages(interview_messages)
        if not messages:
            return "제공된 인터뷰 메시지가 없습니다."

        return "\n".join(
            f"{getattr(message, 'role', 'unknown')}: "
            f"{_truncate_message_content(getattr(message, 'content', ''))}"
            for message in messages[:MAX_INTERVIEW_MESSAGES]
        )
    except Exception:
        return "인터뷰 메시지를 사용할 수 없습니다."


def _sort_interview_messages(interview_messages) -> list:
    if not interview_messages:
        return []
    return sorted(
        interview_messages,
        key=lambda message: getattr(message, "message_order", 0) or 0,
    )


def _is_user_message(message) -> bool:
    role = getattr(message, "role", "")
    role_value = getattr(role, "value", role)
    return str(role_value).lower() == "user"


def _truncate_message_content(content) -> str:
    text = str(content or "").strip()
    if len(text) <= MAX_MESSAGE_CONTENT_LENGTH:
        return text
    return f"{text[:MAX_MESSAGE_CONTENT_LENGTH]}..."


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
