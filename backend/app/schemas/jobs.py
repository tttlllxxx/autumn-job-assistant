from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class JobImport(BaseModel):
    company: str = Field(min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=255)
    description: str = Field(min_length=20)
    url: HttpUrl
    department: str | None = None
    location: str | None = None
    recruitment_type: str | None = None
    graduation_year: str | None = None


class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    company: str
    source_key: str
    external_job_id: str
    title: str
    department: str | None
    location: str | None
    recruitment_type: str | None
    graduation_year: str | None
    description: str
    normalized_url: str
    first_seen_at: datetime
    last_seen_at: datetime
    published_at: datetime | None
    closed: bool
    missing_count: int
    evidence_metadata: dict[str, Any]
    qualification_confirmed: bool


class JobPage(BaseModel):
    items: list[JobOut]
    total: int
    page: int
    page_size: int


class SourceRunRequest(BaseModel):
    source_keys: list[str] | None = None
    allow_browser: bool = True
    max_jobs_per_source: int = Field(default=100, ge=1, le=500)

