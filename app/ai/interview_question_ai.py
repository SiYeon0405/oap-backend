import logging

from app.ai.openai_client import get_openai_client
from app.models.interview_message import InterviewMessage


FALLBACK_QUESTIONS = [
    "이 서비스 이야기를 했을 때 가장 관심을 보인 사람은 누구였나요? (예: 함께 일했던 가게 사장님) 아직 없다면 없다고 답해 주세요.",
    "그분이 해결하려는 일을 직접 보신 적이 있나요? (예: 주문을 종이에 적는 모습을 봤어요) 없다면 없다고 답해 주세요.",
    "대신 쓸 만한 서비스나 방법을 찾아보셨나요? (예: 네이버에서 예약 앱을 찾아봤어요) 없다면 없다고 답해 주세요.",
    "가격이나 돈 버는 방식은 무엇을 보고 정하셨나요? (예: 비슷한 서비스 가격을 봤어요) 아직 없다면 없다고 답해 주세요.",
    "지금까지 이 서비스를 어디에 알려보셨나요? (예: 지인에게 소개했어요) 아직 없다면 없다고 답해 주세요.",
]
FALLBACK_QUESTION = FALLBACK_QUESTIONS[0]
logger = logging.getLogger(__name__)


def _message_contents(messages: list[InterviewMessage], role: str) -> list[str]:
    return [
        message.content.strip()
        for message in messages
        if message.role == role and message.content and message.content.strip()
    ]


def _fallback_question(messages: list[InterviewMessage]) -> str:
    previous_ai_questions = _message_contents(messages, "AI")
    previous_question_set = {question.casefold() for question in previous_ai_questions}
    start_index = len(previous_ai_questions) % len(FALLBACK_QUESTIONS)

    for offset in range(len(FALLBACK_QUESTIONS)):
        question = FALLBACK_QUESTIONS[(start_index + offset) % len(FALLBACK_QUESTIONS)]
        if question.casefold() not in previous_question_set:
            return question

    return FALLBACK_QUESTIONS[-1]


def generate_next_question(
    analysis_request,
    messages: list[InterviewMessage],
) -> str:
    try:
        service_context = {
            key: value
            for key, value in vars(analysis_request).items()
            if not key.startswith("_")
        }
        interview_context = "\n".join(
            f"{message.role}: {message.content}" for message in messages
        )
        previous_ai_questions = "\n".join(
            f"- {question}" for question in _message_contents(messages, "AI")
        )
        answer_contents = _message_contents(messages, "USER")
        user_answers = "\n".join(f"- {answer}" for answer in answer_contents)
        latest_user_answer = answer_contents[-1] if answer_contents else "없음"
        question_step = min(len(_message_contents(messages, "AI")) + 1, 5)
        step_instruction = {
            1: "실제로 관심을 보인 사람이나 검증 이력을 우선 확인하세요.",
            2: "고객의 문제와 현재 방식을 직접 관찰했는지 우선 확인하세요.",
            3: "실제로 찾아본 경쟁 서비스나 대체 방법을 우선 확인하세요.",
            4: "현재 사업 단계와 가격 또는 수익 방식의 결정 근거를 우선 확인하세요.",
            5: "실제 홍보 이력이나 가장 검증하고 싶은 가설을 우선 확인하세요.",
        }[question_step]
        client = get_openai_client()
        response = client.responses.create(
            model="gpt-4.1-mini",
            input=[
                {
                    "role": "system",
                    "content": (
                        "당신은 처음 사업을 시작하는 사람과 이야기합니다. "
                        "개발자 말이나 어려운 말은 쓰지 마세요. 다음 질문 하나만 한국어로 만드세요. "
                        "한 질문에서는 한 가지 내용만 물어보세요. 질문 뒤에는 괄호로 짧고 구체적인 예시 하나를 붙이세요. "
                        "예시는 신청한 서비스와 어울리는 답 하나만 쓰고 여러 선택지를 나열하지 마세요. 전체 문장은 110자 안으로 쓰세요. "
                        "예시 안에서도 '하고', '이며', '와', '과', '또는'으로 두 특징을 연결하지 마세요. "
                        "사용자가 실제로 겪거나 해본 일만 묻고, 미래의 고객 생각이나 행동을 예상하게 하지 마세요. "
                        "해본 적이 없다면 '없다'고 답해도 된다고 알려 주세요. '없다'와 '잘 모르겠다'도 유효한 정보이므로 같은 내용을 다시 캐묻지 마세요. "
                        "서비스 신청 정보와 모든 이전 답변을 먼저 확인해 이미 확보된 사실이나 명시된 부재는 다시 묻지 마세요. "
                        "아직 부족한 정보 중 최종 사업, 시장, 고객, 경쟁, 마케팅 분석에 가장 중요한 한 가지만 동적으로 고르세요. "
                        "이번 단계 지시는 우선순위일 뿐이며 이미 답이 있으면 다음으로 중요한 미확보 정보를 물으세요. 설명, 제목, 번호는 쓰지 마세요. "
                        "사용자의 답을 미리 정하거나 없는 사실을 만들지 마세요. 두 번째 질문부터는 바로 전 사용자의 실제 답변에서 쉬운 표현을 골라 질문에 자연스럽게 넣으세요. "
                        "답변 전체를 억지로 붙이지 말고 질문과 바로 이어지는 핵심 표현만 사용하세요. 문법에 맞는 자연스러운 문장으로 쓰세요. "
                        "이전 AI 질문에 들어 있던 예시는 사용자의 답변이 아니므로 따라 하지 마세요. "
                        "타깃 고객, 세그먼트, 페르소나, Pain Point, BM, 비즈니스 모델, 차별화 요소, 경쟁 우위, "
                        "MVP, KPI, 전환율, 퍼널, 리텐션, 기술 스택, 아키텍처, API, 데이터베이스, "
                        "소상공인, 주 고객, 고객 서비스, SNS, 인터페이스, 응답 속도, 처리 속도, "
                        "온라인 커뮤니티라는 말은 쓰지 마세요."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"서비스 신청 정보:\n{service_context}\n\n"
                        f"지금까지의 대화:\n{interview_context}\n\n"
                        f"이미 한 질문:\n{previous_ai_questions or '- 없음'}\n\n"
                        f"사용자의 답:\n{user_answers or '- 없음'}\n\n"
                        f"반드시 이어서 물어볼 바로 전 사용자 답변:\n{latest_user_answer}\n\n"
                        f"이번에는 {question_step}번째 질문입니다. {step_instruction}"
                    ),
                },
            ],
        )
        next_question = response.output_text.strip()
        return next_question or _fallback_question(messages)
    except Exception as exc:
        error_body = getattr(exc, "body", None)
        error = error_body.get("error", error_body) if isinstance(error_body, dict) else {}
        logger.warning(
            "Interview AI request failed; using fallback error_type=%s error_code=%s",
            type(exc).__name__,
            error.get("code") if isinstance(error, dict) else None,
        )
        return _fallback_question(messages)
