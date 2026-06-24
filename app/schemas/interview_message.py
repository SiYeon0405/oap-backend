from pydantic import BaseModel


class InterviewAnswerRequest(BaseModel):
    answer: str


class InterviewAnswerResponse(BaseModel):
    nextQuestion: str | None
    status: str
    interviewCompleted: bool


class InterviewMessageResponse(BaseModel):
    role: str
    content: str


class InterviewMessagesResponse(BaseModel):
    requestId: int
    status: str
    messages: list[InterviewMessageResponse]
