from pydantic import BaseModel


class InterviewMessageResponse(BaseModel):
    role: str
    content: str


class InterviewMessagesResponse(BaseModel):
    requestId: int
    status: str
    messages: list[InterviewMessageResponse]
