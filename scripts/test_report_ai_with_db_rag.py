import sys
from pathlib import Path
from types import SimpleNamespace


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.ai.report_ai import generate_analysis_report


EXPECTED_KEYS = {
    "service_summary",
    "market_analysis",
    "competitor_analysis",
    "target_customer_analysis",
    "marketing_strategy",
    "platform_recommendation",
}


def main() -> None:
    analysis_request = SimpleNamespace(
        service_name="반려동물 건강관리 앱",
        one_line_description="반려동물 건강 상태를 기록하고 관리하는 모바일 서비스",
        industry="펫테크",
        main_question="인스타그램 광고가 효과가 있을까요?",
    )
    interview_messages = [
        SimpleNamespace(
            role="user",
            content="반려동물 보호자가 예방접종, 체중, 식사, 이상 증상을 기록하게 하고 싶습니다.",
            message_order=1,
        ),
        SimpleNamespace(
            role="user",
            content="초기 고객은 20~40대 강아지와 고양이 보호자를 생각하고 있습니다.",
            message_order=2,
        ),
        SimpleNamespace(
            role="user",
            content="마케팅 예산은 작아서 SNS와 콘텐츠 중심으로 검증하고 싶습니다.",
            message_order=3,
        ),
    ]

    report = generate_analysis_report(
        analysis_request=analysis_request,
        interview_messages=interview_messages,
    )
    report_keys = set(report.keys())

    print(f"report keys: {sorted(report_keys)}")

    missing_keys = EXPECTED_KEYS - report_keys
    if missing_keys:
        raise AssertionError(f"missing report keys: {sorted(missing_keys)}")

    print("report ai db rag test ok")


if __name__ == "__main__":
    main()
