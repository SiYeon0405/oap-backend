import logging

from app.ai.openai_client import get_openai_client
from app.models.interview_message import InterviewMessage


FALLBACK_QUESTIONS = [
    "이 서비스에 대해 다른 사람과 이야기해본 적이 있나요?",
    "이 서비스에 대해 다른 사람에게 이야기해봤다면 어떤 반응을 직접 확인했나요?",
    "이 서비스 대신 사용할 방법이나 서비스를 직접 찾아본 적이 있나요?",
    "가격에 대한 반응을 직접 확인해본 적이 있나요?",
    "지금까지 이 서비스를 실제로 알려본 적이 있나요?",
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
            1: (
                "이 서비스에 대해 다른 사람과 이야기해본 경험이 있는지 "
                "중립적으로 확인하세요."
            ),
            2: (
                "앞선 답변에서 다른 사람과 이야기한 경험이 확인된 경우에만 "
                "그때 직접 확인한 반응을 물어보세요."
            ),
            3: (
                "대신 사용할 방법이나 서비스를 직접 찾아본 경험이 있는지 "
                "중립적으로 확인하세요."
            ),
            4: (
                "가격을 정했다고 전제하지 말고 가격에 대한 반응을 직접 "
                "확인한 경험이 있는지 물어보세요."
            ),
            5: (
                "이 서비스를 실제로 알려본 경험이 있는지 물어보세요. "
                "앞으로 어디에 알릴지는 묻지 마세요."
            ),
        }[question_step]
        client = get_openai_client()
        response = client.responses.create(
            model="gpt-5-mini",
            input=[
                {
                    "role": "system",
                    "content": (
                        "당신은 처음 사업을 시작하는 사람과 이야기합니다. "
                        "개발자 말이나 어려운 말은 쓰지 마세요. 다음 질문 하나만 한국어로 만드세요. "
                        "가장 중요한 원칙: 사용자가 이미 겪은 일과 실제로 해본 일만 물어보세요. "
                        "앞으로 어떻게 될지, 고객이 어떻게 생각할지 같은 예상은 절대 묻지 마세요. "
                        "겪은 일을 물어야 실제 답이 나옵니다. "
                        "사용자가 말하지 않은 경험이나 사실이 있다고 전제하지 마세요. "
                        "확인되지 않은 영역은 그 경험이 있었는지부터 중립적으로 물어보세요. "
                        "답변 예시, 답변 후보, 선택지, 특정 답변을 요구하는 안내를 질문에 넣지 마세요. "
                        "한 질문에서는 한 가지 내용만 물어보세요. 전체 문장은 110자 안으로 쓰세요. "
                        "설명, 제목, 번호는 쓰지 마세요. "
                        "이미 물은 내용은 다시 묻지 말고 사용자의 답을 미리 정하거나 없는 사실을 만들지 마세요. "
                        "질문 후보 영역은 관심을 보인 사람, 그 사람이 지금 하는 방식, 찾아본 대안, "
                        "가격을 정한 기준, 지금까지 알려본 곳입니다. "
                        "이미 확보되었거나 사용자가 없다고 답한 항목은 건너뛰세요. "
                        "아직 확보되지 않은 정보 중 최종 분석 결과에 가장 큰 영향을 주는 한 가지를 선택해 질문하세요. "
                        "미리 정해진 질문 순서를 기계적으로 따르지 마세요. "
                        "두 번째 질문부터는 바로 전 사용자의 실제 답변에서 쉬운 표현을 골라 질문에 자연스럽게 넣으세요. "
                        "답변 전체를 억지로 붙이지 말고 질문과 바로 이어지는 핵심 표현만 사용하세요. 문법에 맞는 자연스러운 문장으로 쓰세요. "
                        "사용자가 '없어요'나 '잘 모르겠어요'라고 답했다면 그 답을 존중하고 "
                        "다음 미확보 정보를 질문하세요. 같은 내용을 다시 캐묻지 마세요. "
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
                        f"이번에는 최대 5개 질문 중 {question_step}번째 질문입니다. "
                        f"다음은 우선 확인할 후보 영역입니다. 이미 답이 있거나 없다고 답했다면 건너뛰세요. {step_instruction}"
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
