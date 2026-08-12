import logging

from app.ai.openai_client import get_openai_client
from app.models.interview_message import InterviewMessage


FALLBACK_QUESTIONS = [
    "이 서비스 이야기를 해본 사람 중에 가장 관심을 보인 분은 누구였나요? (예: 같이 창업 준비하는 친구) 아직 없으면 '없어요'라고 답해도 됩니다.",
    "그분이 지금 그 일을 어떻게 하고 있는지 직접 보신 적 있나요? (예: 엑셀에 하나씩 옮겨 적더라고요) 못 보셨으면 '못 봤어요'라고 답해도 됩니다.",
    "이 서비스 대신 쓸 만한 걸 찾아보신 적 있나요? 뭐가 나왔나요? (예: 비슷한 앱이 두 개 있었어요) 안 찾아보셨으면 '없어요'라고 답해도 됩니다.",
    "가격은 어떻게 정하셨나요? 무엇을 보고 그렇게 정하셨나요? (예: 비슷한 서비스가 오만 원이라 그보다 낮게 잡았어요) 아직 안 정하셨으면 '아직이요'라고 답해도 됩니다.",
    "지금까지 이 서비스를 알려본 곳이 있나요? (예: 아는 사람들한테만 말해봤어요) 없으면 '없어요'라고 답해도 됩니다.",
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
                "이 서비스 이야기를 해본 사람 중 가장 관심을 보인 사람이 "
                "누구였는지 물어보세요. 아직 아무에게도 말해보지 않았으면 "
                "'없다'고 답해도 된다고 알려 주세요."
            ),
            2: (
                "앞에서 말한 그 사람이 지금 그 일을 어떻게 하고 있는지 "
                "직접 본 적이 있는지 물어보세요. 못 봤으면 '못 봤다'고 "
                "답해도 된다고 알려 주세요."
            ),
            3: (
                "이 서비스 대신 쓸 만한 것을 찾아본 적이 있는지, "
                "찾아봤다면 무엇이 나왔는지 물어보세요. "
                "이름을 아는 만큼만 말해도 된다고 알려 주세요."
            ),
            4: (
                "가격을 어떻게 정했는지, 무엇을 보고 그렇게 정했는지 "
                "물어보세요. 아직 안 정했으면 '아직'이라고 답해도 된다고 "
                "알려 주세요."
            ),
            5: (
                "지금까지 이 서비스를 알려본 곳이 있는지 물어보세요. "
                "없으면 '없다'고 답해도 된다고 알려 주세요. "
                "앞으로 어디에 알릴지는 묻지 마세요."
            ),
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
                        "가장 중요한 원칙: 사용자가 이미 겪은 일과 실제로 해본 일만 물어보세요. "
                        "앞으로 어떻게 될지, 고객이 어떻게 생각할지 같은 예상은 절대 묻지 마세요. "
                        "사용자는 이제 막 시작한 사람이라 예상을 물으면 '잘 모르겠다'고만 답합니다. "
                        "겪은 일을 물어야 실제 답이 나옵니다. "
                        "해본 적이 없거나 아직 없는 일이면 '없다'고 답해도 된다고 알려 주세요. "
                        "'없다'는 답도 중요한 정보이므로 억지로 답을 끌어내지 마세요. "
                        "한 질문에서는 한 가지 내용만 물어보세요. 질문 뒤에는 괄호로 짧고 구체적인 예시 하나를 붙이세요. "
                        "예시는 신청한 서비스와 어울리는 답 하나만 쓰고 여러 선택지를 나열하지 마세요. 전체 문장은 110자 안으로 쓰세요. "
                        "예시 안에서도 '하고', '이며', '와', '과', '또는'으로 두 특징을 연결하지 마세요. "
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
