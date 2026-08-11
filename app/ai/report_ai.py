import json

from app.ai.openai_client import get_openai_client
from app.ai.report_retriever import (
    retrieve_report_knowledge,
    retrieve_report_knowledge_with_audit,
)
from app.schemas.analysis_report import (
    AIAnalysisReportPayload,
    CompetitorAnalysisSection,
    MarketAnalysisSection,
    MarketingStrategySection,
    Metric,
    KPI,
    RankedPlatform,
    PlatformRecommendationSection,
    ReportSection,
    TargetCustomerAnalysisSection,
)


REPORT_KEYS = (
    "service_summary",
    "market_analysis",
    "competitor_analysis",
    "target_customer_analysis",
    "marketing_strategy",
    "platform_recommendation",
)
SECTION_MODELS = {
    "service_summary": ReportSection,
    "market_analysis": MarketAnalysisSection,
    "competitor_analysis": CompetitorAnalysisSection,
    "target_customer_analysis": TargetCustomerAnalysisSection,
    "marketing_strategy": MarketingStrategySection,
    "platform_recommendation": PlatformRecommendationSection,
}
MAX_MESSAGE_CONTENT_LENGTH = 500
MAX_INTERVIEW_MESSAGES = 20


def generate_analysis_report(
    analysis_request,
    interview_messages=None,
    evidence_context: str | None = None,
) -> dict[str, dict]:
    report, _ = generate_analysis_report_with_citations(
        analysis_request,
        interview_messages,
        evidence_context=evidence_context,
    )
    return report


def generate_analysis_report_with_citations(
    analysis_request,
    interview_messages=None,
    evidence_context: str | None = None,
) -> tuple[dict[str, dict], dict[str, list[int]]]:
    try:
        response_text = _request_analysis_report(
            analysis_request,
            interview_messages,
            evidence_context=evidence_context,
        )
        report = json.loads(response_text)
        if _is_valid_report(report):
            report = sanitize_report_payload(report)
            return (
                _strip_report_citations(report),
                _extract_section_citations(report),
            )
    except (json.JSONDecodeError, TypeError, ValueError):
        return _generate_fallback_analysis_report(analysis_request), _empty_citations()

    return _generate_fallback_analysis_report(analysis_request), _empty_citations()


def generate_analysis_report_with_audit(
    analysis_request,
    interview_messages=None,
) -> tuple[dict[str, dict], int | None]:
    report, _, retrieval_run_id = generate_analysis_report_with_audit_and_citations(
        analysis_request,
        interview_messages,
    )
    return report, retrieval_run_id


def generate_analysis_report_with_audit_and_citations(
    analysis_request,
    interview_messages=None,
) -> tuple[dict[str, dict], dict[str, list[int]], int | None]:
    retrieval_query = build_report_retrieval_query(
        analysis_request,
        interview_messages,
    )
    evidence_context, retrieval_run_id = retrieve_report_knowledge_with_audit(
        retrieval_query,
        getattr(analysis_request, "id", None),
    )
    report, citations = generate_analysis_report_with_citations(
        analysis_request,
        interview_messages,
        evidence_context=evidence_context,
    )
    return report, citations, retrieval_run_id


def _request_analysis_report(
    analysis_request,
    interview_messages=None,
    evidence_context: str | None = None,
) -> str:
    service_context = _build_service_context(analysis_request)
    user_answer_context = _build_user_answer_context(interview_messages)
    interview_context = _build_interview_context(interview_messages)
    rag_context = evidence_context
    if rag_context is None:
        rag_context = retrieve_report_knowledge(
            build_report_retrieval_query(analysis_request, interview_messages)
        )

    client = get_openai_client()
    response = client.responses.create(
        model="gpt-4.1-mini",
        text={
            "format": {
                "type": "json_schema",
                "name": "oap_report_v3",
                "schema": AIAnalysisReportPayload.model_json_schema(),
                "strict": False,
            }
        },
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
                            "아래 Retrieved Knowledge는 외부 Evidence입니다. 사실 주장과 수치는 이를 직접 뒷받침하는 "
                            "내용이 있을 때만 사용하세요. 서비스 기본 정보는 사업 자체의 사실로, 인터뷰 답변은 사용자의 "
                            "경험과 실행 이력으로 사용하고, 시장에 관한 주관적 예상보다 검증된 Evidence를 우선하세요.\n\n"
                            "Use the Evidence below as priority reference material, "
                            "but do not state claims as certain when the Evidence does "
                            "not support them. Use only the exact Evidence IDs shown "
                            "below when returning section evidence_ids. Do not invent "
                            "Evidence IDs. Sections based only on AI analysis or "
                            "strategy may return an empty evidence_ids list. Keep the "
                            "existing section fields and add evidence_ids as a list of "
                            "integers inside each section object. When a factual claim "
                            "uses Retrieved Knowledge, the containing section and its "
                            "related visualization item must include the exact supporting "
                            "Evidence ID. Do not omit an ID for evidence you actually use.\n\n"
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
                    "서비스 기본 정보는 사업 정의에, 인터뷰 답변은 실제 경험과 실행 이력에, "
                    "Retrieved Knowledge는 외부 사실 검증에 사용하세요. 서로 충돌하면 차이를 숨기지 말고 "
                    "검증된 Evidence가 뒷받침하는 시장 사실과 사용자의 주관적 판단을 구분하세요.\n\n"
                    "반환 JSON의 최상위 key는 다음 7개만 사용하세요:\n"
                    "- service_summary\n"
                    "- market_analysis\n"
                    "- competitor_analysis\n"
                    "- target_customer_analysis\n"
                    "- marketing_strategy\n"
                    "- platform_recommendation\n"
                    "- headlineMetrics\n\n"
                    "headlineMetrics는 배열이고 나머지 6개 key의 value는 object여야 합니다. "
                    "각 섹션 object에는 title, summary, insights, recommendations를 포함하세요. "
                    "insights와 recommendations는 문자열 배열로 작성하세요. "
                    "각 object에는 evidence_ids도 포함할 수 있으며, 값은 위 Evidence ID 중 "
                    "실제로 참고한 정수 ID 배열이어야 합니다. 기존 필드는 유지하면서 계약의 "
                    "시각화 필드를 정확한 camelCase key로 추가하세요."
                ),
            },
            {
                "role": "user",
                "content": (
                    "추가 작성 기준을 반드시 따르세요.\n\n"
                    "전체 리포트 기준:\n"
                    "- 대한민국 시장 기준으로 작성하세요.\n"
                    "- 초기 창업자와 소규모 브랜드가 실행할 수 있는 수준으로 작성하세요.\n"
                    "- 서비스 기본 정보와 인터뷰 답변의 구체적인 표현을 적극 반영하세요.\n"
                    "- 사실, 사용자 경험, 전략적 추론을 구분하고 모르는 사실은 단정하지 마세요.\n"
                    "- 시장 규모, 성장률, 점유율, 비용, 사용자 수 등은 Evidence가 직접 뒷받침할 때만 정확한 숫자로 쓰세요.\n"
                    "- Evidence가 부족하면 추정임을 밝히고 숫자, 출처, 참고문헌을 만들지 마세요.\n"
                    "- 같은 내용을 여러 섹션에 복사하지 말고 각 섹션의 판단을 다음 섹션의 실행안과 일관되게 연결하세요.\n"
                    "- 다른 서비스에도 그대로 적용되는 일반론과 동어반복을 쓰지 마세요.\n"
                    "- 결과는 반드시 JSON object만 반환하고 markdown 코드블록은 사용하지 마세요.\n"
                    "- JSON 최상위 key는 기존 6개만 사용하고, 모든 value는 dict 타입을 유지하세요.\n\n"
                    "competitor_analysis 작성 기준:\n"
                    "- 대한민국 시장 기준으로 분석하세요.\n"
                    "- 인터뷰나 Evidence에서 확인된 실제 국내 서비스, 플랫폼, 기업만 언급하세요.\n"
                    "- 확인되지 않은 기업을 만들지 말고, 직접 경쟁사와 대체재를 구분하세요.\n"
                    "- 해외 기업 중심 분석은 금지하세요.\n"
                    "- 각 경쟁 대상마다 경쟁사/경쟁 채널명, 강점, 약점, 우리 서비스의 차별화 지점, 초기 창업자 관점의 대응 전략을 포함하세요.\n\n"
                    "platform_recommendation 작성 기준:\n"
                    "- 단순히 특정 플랫폼이 좋다는 수준으로 쓰지 말고 추천 우선순위 형태로 작성하세요.\n"
                    "- 업종과 인터뷰 답변에 맞는 국내 사용 가능 플랫폼을 고르세요.\n"
                    "- 타깃 고객, 서비스 특성, 고객의 탐색·구매 행동, 콘텐츠 유형, 현재 사업 단계를 함께 근거로 고르세요.\n"
                    "- 오프라인 매장이 아닌 서비스에는 네이버 플레이스, 카카오맵, 지역 제휴, 매장 방문, 단골 쿠폰을 추천하지 마세요.\n"
                    "- 구독형 서비스에는 재방문 대신 구독 유지와 이탈 방지 관점으로 작성하세요.\n"
                    "- 각 플랫폼마다 서로 다른 추천 이유와 고객 단계, 저예산 실행 방법, 기대 효과, 주의할 점을 포함하세요.\n\n"
                    "marketing_strategy 작성 기준:\n"
                    "- 추상적 조언을 피하고 1개월, 2개월, 3개월 실행 계획 형태로 작성하세요.\n"
                    "- 각 월별로 목표, 실행 액션, 사용할 채널, 측정할 KPI, 주의할 리스크를 포함하세요.\n"
                    "- 무엇을, 누구에게, 어느 채널에서, 어떤 메시지로 실행하고 무엇을 측정할지 구체적으로 연결하세요.\n"
                    "- 각 단계는 이전 단계의 측정 결과에 따라 다음 행동을 결정하도록 작성하세요.\n"
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
                    "\n- insights는 서비스 정보, 인터뷰 또는 Evidence에 연결하고 다른 서비스에도 그대로 적용되는 문장을 쓰지 마세요."
                    "\n- recommendations는 구체적 행동, 채널·대상, 판단 이유를 포함하고 '~할 것' 한 문장으로 끝내지 마세요."
                    "\n- score는 0~100 또는 null, confidence와 rate는 0~1 또는 null입니다."
                    "\n- 근거 없는 숫자, sampleSize, dataAsOf, 백분위, URL, 시계열을 추측하지 마세요."
                    "\n- 관측값은 observed, 공식 계산값은 derived, 정성 수치화는 estimated로 표시하세요."
                    "\n- 정성 수치화 calculation에는 '정성 근거를 기반으로 한 AI 추정'을 포함하세요."
                    "\n- 실제 추세 데이터가 없으면 series는 빈 배열로, 실제 캠페인 데이터가 없으면 P2 필드는 null로 반환하세요."
                    "\n- competitive_intensity direction은 lower_is_better입니다."
                    "\n- evidenceIds에는 제공된 Evidence ID만 사용하세요."
                    "\n\n시각화 계약:\n"
                    "- headlineMetrics: market_attractiveness, competitive_intensity, target_clarity만 생성하세요. evidence_coverage는 서버가 계산합니다.\n"
                    "- market_analysis: metrics, purchaseFactors, opportunityMatrix, demandTrend를 추가하세요. 실제 기간 데이터가 없으면 demandTrend.series=[]입니다.\n"
                    "- competitor_analysis: competitorCount, analyzedCopyCount, messageCoverage, competitors를 추가하세요. 실제 조사 count가 없으면 null입니다.\n"
                    "- target_customer_analysis: segments와 scoringModelVersion=target-priority-v1.0을 추가하세요. 4개 하위 점수가 모두 있을 때만 명시된 가중식으로 priorityScore를 계산하세요.\n"
                    "- marketing_strategy: executionPhases를 30일 내 순차 단계로 추가하고 KPI마다 calculation, measurementWindow, decisionRule을 포함하세요.\n"
                    "- platform_recommendation: rankedPlatforms를 추가하고 scoringModelVersion=channel-fit-v1.0, 동일 scoreWeights와 scoreBreakdown을 사용하세요.\n"
                    "- opportunityMatrix 좌표는 0~100 분석 점수이며 근거가 없으면 point를 만들지 마세요.\n"
                    "- competitors의 website와 priceRange는 확인 가능한 근거가 없으면 null입니다.\n"
                    "- currentKpiValue, targetAchievementRate, previousReportDelta, actualCampaignPerformance, recommendationOutcomeGap은 실제 연동 데이터가 없으면 null입니다.\n"
                    "- 기존 recommendations의 타입과 내용을 바꾸지 마세요."
                ),
            },
        ],
    )
    return response.output_text.strip()


def build_report_retrieval_query(analysis_request, interview_messages=None) -> str:
    service_context = _build_service_context(analysis_request)
    parts = [
        ("service_name", service_context.get("service_name")),
        ("service_description", service_context.get("one_line_description")),
        ("industry_or_category", service_context.get("industry")),
        ("analysis_purpose", service_context.get("main_question")),
    ]
    query_lines = [
        f"{label}: {str(value).strip()}"
        for label, value in parts
        if str(value or "").strip()
    ]

    user_answers = _build_user_answers_for_query(interview_messages)
    if user_answers:
        query_lines.append(f"user_interview_answers: {user_answers}")

    return "\n".join(query_lines)


def build_report_evidence_context(evidences: list[dict]) -> str:
    blocks = []
    for index, evidence in enumerate(evidences, start=1):
        content = str(evidence.get("content") or "").strip()
        if not content:
            continue

        rank = evidence.get("rank") or index
        evidence_id = evidence.get("retrieval_evidence_id")
        source = _build_evidence_source(evidence)
        label = (
            f"[Evidence ID: {evidence_id}]"
            if evidence_id is not None
            else f"[Evidence {rank}]"
        )
        blocks.append(
            "\n".join(
                [
                    label,
                    f"출처: {source}",
                    f"내용: {content}",
                ]
            )
        )

    return "\n\n".join(blocks)


def _build_evidence_source(evidence: dict) -> str:
    metadata = evidence.get("metadata") or {}
    source_parts = []
    if evidence.get("document_id") is not None:
        source_parts.append(f"document_id={evidence.get('document_id')}")
    if evidence.get("chunk_index") is not None:
        source_parts.append(f"chunk_index={evidence.get('chunk_index')}")

    for key in ("title", "source", "source_path", "domain", "category"):
        value = metadata.get(key)
        if value:
            source_parts.append(f"{key}={value}")

    scores = evidence.get("scores") or {}
    score_parts = [
        f"{key}={value:.4f}" if isinstance(value, float) else f"{key}={value}"
        for key, value in scores.items()
        if value is not None
    ]
    if score_parts:
        source_parts.append(f"scores({', '.join(score_parts)})")

    return ", ".join(source_parts) if source_parts else "unknown"


def _strip_report_citations(report: dict) -> dict[str, dict]:
    sanitized_report = {}
    for key in REPORT_KEYS:
        section = dict(report[key])
        section.pop("evidence_ids", None)
        sanitized_report[key] = section
    return sanitized_report


def _extract_section_citations(report: dict) -> dict[str, list[int]]:
    citations = {}
    for key in REPORT_KEYS:
        citations[key] = _collect_evidence_ids(report.get(key, {}))
    return citations


def _collect_evidence_ids(value) -> list[int]:
    collected = []
    if isinstance(value, dict):
        collected.extend(_normalize_evidence_ids(value.get("evidenceIds", [])))
        collected.extend(_normalize_evidence_ids(value.get("evidence_ids", [])))
        for nested_key, nested_value in value.items():
            if nested_key not in {"evidenceIds", "evidence_ids"}:
                collected.extend(_collect_evidence_ids(nested_value))
    elif isinstance(value, list):
        for item in value:
            collected.extend(_collect_evidence_ids(item))
    return list(dict.fromkeys(collected))


def _normalize_evidence_ids(value) -> list[int]:
    if not isinstance(value, list):
        return []

    normalized_ids = []
    seen = set()
    for item in value:
        if not isinstance(item, int) or item in seen:
            continue
        seen.add(item)
        normalized_ids.append(item)
    return normalized_ids


def _empty_citations() -> dict[str, list[int]]:
    return {key: [] for key in REPORT_KEYS}


def sanitize_report_payload(report: dict) -> dict[str, dict]:
    sanitized = {}
    for section_key, model in SECTION_MODELS.items():
        raw_section = _normalize_ai_section(section_key, report.get(section_key, {}))
        visual_fields = [
            field_name
            for field_name in model.model_fields
            if field_name not in ReportSection.model_fields
        ]
        base_payload = {
            key: value
            for key, value in raw_section.items()
            if key not in visual_fields
        }
        section = model.model_validate(ReportSection.model_validate(base_payload).model_dump())
        accepted = section.model_dump(mode="json")
        for field_name in visual_fields:
            if field_name not in raw_section:
                continue
            candidate = {**accepted, field_name: raw_section[field_name]}
            try:
                section = model.model_validate(candidate)
            except ValueError:
                continue
            accepted = section.model_dump(mode="json")
        sanitized[section_key] = accepted
    headline_metrics = []
    for raw_metric in report.get("headlineMetrics", []):
        try:
            headline_metrics.append(Metric.model_validate(raw_metric).model_dump(mode="json"))
        except ValueError:
            continue
    sanitized["headline_metrics"] = headline_metrics
    return sanitized


def _normalize_ai_section(section_key: str, raw_section: dict) -> dict:
    section = dict(raw_section) if isinstance(raw_section, dict) else {}
    if section_key == "target_customer_analysis":
        version = section.get("scoringModelVersion") or "target-priority-v1.0"
        normalized_segments = []
        for index, raw_segment in enumerate(section.get("segments") or []):
            if not isinstance(raw_segment, dict):
                continue
            segment = dict(raw_segment)
            segment["scoringModelVersion"] = version
            components = [
                segment.get("problemFrequencyScore"),
                segment.get("purchaseIntentScore"),
                segment.get("reachabilityScore"),
                segment.get("priceSensitivityScore"),
            ]
            if all(isinstance(value, (int, float)) for value in components):
                segment["priorityScore"] = (
                    components[0] * 0.35
                    + components[1] * 0.35
                    + components[2] * 0.20
                    + (100 - components[3]) * 0.10
                )
            segment["_inputOrder"] = index
            normalized_segments.append(segment)
        normalized_segments = [
            item for item in normalized_segments if item.get("priorityScore") is not None
        ]
        normalized_segments.sort(
            key=lambda item: (-item["priorityScore"], item["_inputOrder"])
        )
        for rank, segment in enumerate(normalized_segments, start=1):
            segment["rank"] = rank
            segment.pop("_inputOrder", None)
        section["segments"] = normalized_segments
        section["scoringModelVersion"] = version
    elif section_key == "marketing_strategy":
        phases = []
        for raw_phase in section.get("executionPhases") or []:
            if not isinstance(raw_phase, dict):
                continue
            phase = dict(raw_phase)
            valid_kpis = []
            for raw_kpi in phase.get("kpis") or []:
                try:
                    valid_kpis.append(KPI.model_validate(raw_kpi).model_dump(mode="json"))
                except ValueError:
                    continue
            phase["kpis"] = valid_kpis
            phases.append(phase)
        section["executionPhases"] = phases
    elif section_key == "platform_recommendation":
        version = section.get("scoringModelVersion") or "channel-fit-v1.0"
        normalized_platforms = []
        for index, raw_platform in enumerate(section.get("rankedPlatforms") or []):
            if not isinstance(raw_platform, dict):
                continue
            platform = dict(raw_platform)
            platform["scoringModelVersion"] = version
            breakdown = platform.get("scoreBreakdown")
            weights = platform.get("scoreWeights")
            if isinstance(breakdown, dict) and isinstance(weights, dict):
                keys = (
                    "audienceFit",
                    "contentFormatFit",
                    "costEfficiency",
                    "conversionIntent",
                    "executionFeasibility",
                )
                if all(isinstance(breakdown.get(key), (int, float)) for key in keys) and all(
                    isinstance(weights.get(key), (int, float)) for key in keys
                ):
                    platform["score"] = sum(
                        breakdown[key] * weights[key] for key in keys
                    )
            platform["_inputOrder"] = index
            try:
                validated = RankedPlatform.model_validate(platform).model_dump(mode="json")
            except ValueError:
                platform.pop("scoreBreakdown", None)
                platform.pop("scoreWeights", None)
                try:
                    validated = RankedPlatform.model_validate(platform).model_dump(mode="json")
                except ValueError:
                    continue
            validated["_inputOrder"] = index
            normalized_platforms.append(validated)
        normalized_platforms = [
            item for item in normalized_platforms if item.get("score") is not None
        ]
        normalized_platforms.sort(
            key=lambda item: (-item["score"], item["_inputOrder"])
        )
        for rank, platform in enumerate(normalized_platforms, start=1):
            platform["priority_rank"] = rank
            platform.pop("_inputOrder", None)
        section["rankedPlatforms"] = normalized_platforms
    return section


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


def _build_user_answers_for_query(interview_messages) -> str:
    messages = _sort_interview_messages(interview_messages)
    user_messages = [
        _truncate_message_content(getattr(message, "content", ""))
        for message in messages
        if _is_user_message(message)
    ]
    return " ".join(message for message in user_messages if message)


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
