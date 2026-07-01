from openai import OpenAI

from app.models.interview_message import InterviewMessage


FALLBACK_QUESTIONS = [
    "현재 주요 기능은 무엇인가요?",
    "가장 중요한 사용자 흐름은 무엇인가요?",
    "운영 중 자주 발생하는 문제는 무엇인가요?",
    "외부 시스템과 연동되는 부분은 무엇인가요?",
    "가장 개선이 필요한 기능은 무엇인가요?",
    "사용자가 자주 요청하는 개선사항은 무엇인가요?",
]
FALLBACK_QUESTION = FALLBACK_QUESTIONS[0]


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

    return f"추가로 확인할 차별화 포인트는 무엇인가요? {len(previous_ai_questions) + 1}"


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
        user_answers = "\n".join(
            f"- {answer}" for answer in _message_contents(messages, "USER")
        )
        client = OpenAI()
        response = client.responses.create(
            model="gpt-4.1-mini",
            input=[
                {
                    "role": "system",
                    "content": (
                        "당신은 서비스 분석 인터뷰 질문을 생성하는 전문가입니다. "
                        "다음 질문 1개만 한국어로 생성하세요. "
                        "40자 이내로 작성하고, 인사말/설명/번호 없이 질문 문장만 반환하세요. "
                        "이전 AI 질문과 동일하거나 유사한 질문은 절대 하지 마세요. "
                        "사용자 답변을 참고해 아직 확인하지 않은 내용을 물어보세요."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"사용자 서비스 정보:\n{service_context}\n\n"
                        f"기존 인터뷰 메시지:\n{interview_context}\n\n"
                        f"이전 AI 질문 목록:\n{previous_ai_questions or '- 없음'}\n\n"
                        f"사용자 답변 목록:\n{user_answers or '- 없음'}\n\n"
                        "위 이전 AI 질문과 중복되거나 유사하지 않은 다음 질문 1개를 생성하세요."
                    ),
                },
            ],
        )
        next_question = response.output_text.strip()
        return next_question or _fallback_question(messages)
    except Exception:
        return _fallback_question(messages)
