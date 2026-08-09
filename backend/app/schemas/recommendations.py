from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.jobs import JobOut


class LLMJobScore(BaseModel):
    job_id: int
    score: float = Field(ge=0, le=40)
    matching_facts: list[str] = []
    gaps: list[str] = []
    risks: list[str] = []
    jd_quotes: list[str] = []
    fact_ids: list[str] = []

    @field_validator("matching_facts", "gaps", "risks", "jd_quotes", "fact_ids", mode="before")
    @classmethod
    def accept_single_string_as_one_item(cls, value):
        # JSON-only providers sometimes collapse a one-item array into a
        # string. Preserve the content and normalize it at the schema edge.
        return [value] if isinstance(value, str) else value


class LLMBatchResponse(BaseModel):
    scores: list[LLMJobScore]


class RecommendationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    job_id: int
    version: int
    hard_filter_passed: bool
    hard_filter_details: dict[str, Any]
    qualification_pending: bool
    rule_score: float
    vector_score: float
    llm_score: float | None
    final_score: float
    rerank_status: str
    evidence: dict[str, Any]
    model_name: str | None
    prompt_version: str
    scoring_version: str
    estimated_cost_rmb: float | None
    created_at: datetime


class RecommendationWithJobOut(RecommendationOut):
    job: JobOut


class RecommendationPage(BaseModel):
    items: list[RecommendationWithJobOut]
    total: int
    page: int
    page_size: int
    counts: dict[str, int]
    updated_at: datetime | None = None


class FeedbackRequest(BaseModel):
    action: str = Field(pattern="^(favorite|ignore|suitable|unsuitable|confirm_qualification|reset_weights)$")
    reason: str | None = Field(default=None, max_length=255)
