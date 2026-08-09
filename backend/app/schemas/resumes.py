from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class FactOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    fact_id: str
    category: str
    redacted_text: str
    page_number: int | None
    line_number: int | None
    active: bool
    confirmed: bool
    confidence: float
    supersedes_fact_id: str | None


class ResumeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    original_name: str
    media_type: str
    content_hash: str
    parse_status: str
    parse_error: str | None
    created_at: datetime
    facts: list[FactOut] = []


class ProfileUpdate(BaseModel):
    target_directions: list[str] | None = None
    skills: list[str] | None = None
    education_level: str | None = None
    experience_summary: str | None = None
    project_summary: str | None = None
    target_cities: list[str] | None = None
    target_graduation_year: str | None = Field(default=None, pattern=r"^20\d{2}$")
    target_recruitment_types: list[str] | None = None
    remote_preference: str | None = None
    exclude_keywords: list[str] | None = None


class ProfileOut(ProfileUpdate):
    model_config = ConfigDict(from_attributes=True)
    id: int
    confirmed: bool
    version: int
    updated_at: datetime


class FactAction(BaseModel):
    action: str = Field(pattern="^(confirm|disable|revise)$")
    text: str | None = Field(default=None, max_length=1000)
