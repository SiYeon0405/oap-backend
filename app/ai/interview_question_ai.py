from openai import OpenAI

from app.models.interview_message import InterviewMessage


FALLBACK_QUESTION = "현재 주요 기능은 무엇인가요?"


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
        client = OpenAI()
        response = client.responses.create(
            model="gpt-4.1-mini",
            input=[
                {
                    "role": "system",
                    "content": (
                        "당신은 서비스 분석 인터뷰 질문을 생성하는 전문가입니다. "
                        "다음 질문 1개만 한국어로 생성하세요. "
                        "40자 이내로 작성하고, 인사말/설명/번호 없이 질문 문장만 반환하세요."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"사용자 서비스 정보:\n{service_context}\n\n"
                        f"기존 인터뷰 메시지:\n{interview_context}\n\n"
                        "위 내용을 바탕으로 다음 질문 1개를 생성하세요."
                    ),
                },
            ],
        )
        next_question = response.output_text.strip()
        return next_question or FALLBACK_QUESTION
    except Exception:
        return FALLBACK_QUESTION
