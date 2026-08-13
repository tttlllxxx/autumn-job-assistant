from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class TailoredSentence(BaseModel):
    text: str = Field(min_length=2, max_length=2000)
    fact_ids: list[str] = Field(min_length=1)


class TailorRequest(BaseModel):
    confirmed: bool
    sentences: list[TailoredSentence] | None = None


class TailorLLMResponse(BaseModel):
    sentences: list[TailoredSentence] = Field(min_length=1)


class TailorAdviceRewrite(BaseModel):
    fact_id: str
    action: str = Field(min_length=2, max_length=240)
    revised_text: str = Field(min_length=2, max_length=2000)
    rationale: str = Field(min_length=2, max_length=300)


class TailorAdviceLLMResponse(BaseModel):
    rewrites: list[TailorAdviceRewrite] = Field(min_length=1)


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


class TailorSuggestionOut(BaseModel):
    section: str
    action: str
    current_text: str
    suggested_text: str
    rationale: str
    jd_quote: str | None = None


class TailorAdviceOut(BaseModel):
    job: dict[str, Any]
    recommendation_version: int
    updated_at: datetime
    suggestions: list[TailorSuggestionOut]
    gaps: list[str]


class TailorAdviceSummaryOut(BaseModel):
    job: dict[str, Any]
    recommendation_version: int
    updated_at: datetime
    suggestion_count: int
