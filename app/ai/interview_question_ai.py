import logging

from app.ai.openai_client import get_openai_client
from app.models.interview_message import InterviewMessage


FALLBACK_QUESTIONS = [
    "누가 이 서비스를 가장 많이 쓸까요? (예: 혼자 가게를 운영하는 사장님) 잘 모르겠으면 '잘 모르겠어요'라고 답해도 됩니다.",
    "그 사람은 어떤 일 때문에 가장 불편한가요? (예: 주문을 손으로 적느라 자주 빠뜨려요) 잘 모르겠으면 넘어가도 됩니다.",
    "그 사람은 지금 그 불편을 어떻게 해결하나요? (예: 종이에 적거나 엑셀을 써요) 잘 모르겠으면 넘어가도 됩니다.",
    "그 사람이 서비스를 고를 때 가장 중요하게 보는 것은 무엇인가요? (예: 가격이 알맞은 것) 잘 모르겠으면 넘어가도 됩니다.",
    "그 사람은 이 서비스를 어디에서 처음 알게 될까요? (예: 인터넷 검색이나 친구 소개) 잘 모르겠으면 넘어가도 됩니다.",
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
            1: "이 서비스를 가장 많이 쓸 사람이 누구인지 물어보세요.",
            2: "그 사람이 가장 불편해하는 일이 무엇인지 물어보세요.",
            3: "그 사람이 그 불편을 지금 어떻게 해결하는지 물어보세요.",
            4: "그 사람이 서비스를 고를 때 가장 중요하게 보는 한 가지를 물어보세요.",
            5: "그 사람이 이 서비스를 어디에서 처음 알게 될지 물어보세요.",
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
                        "마지막에는 잘 모르겠으면 넘어가도 된다고 알려 주세요. 설명, 제목, 번호는 쓰지 마세요. "
                        "이미 물은 내용은 다시 묻지 말고 사용자의 답을 미리 정하거나 없는 사실을 만들지 마세요. "
                        "질문 순서는 고객, 고객의 가장 큰 불편, 지금 쓰는 해결법, 서비스를 고르는 기준, 서비스를 알게 되는 곳입니다. "
                        "순서를 건너뛰지 마세요. 두 번째 질문부터는 바로 전 사용자의 실제 답변에서 쉬운 표현을 골라 질문에 자연스럽게 넣으세요. "
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
