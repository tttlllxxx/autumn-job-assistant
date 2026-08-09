from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class TailoredSentence(BaseModel):
    text: str = Field(min_length=2, max_length=500)
    fact_ids: list[str] = Field(min_length=1)


class TailorRequest(BaseModel):
    confirmed: bool
    sentences: list[TailoredSentence] | None = None


class TailorLLMResponse(BaseModel):
    sentences: list[TailoredSentence] = Field(min_length=1)


class ResumeVersionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    job_id: int
    markdown_content: str
    status: str
    fact_ids: list[str]
    template_version: str
    validation_result: dict
    created_at: datetime
    has_pdf: bool = False

