from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


class ApplicationInput(BaseModel):
    company: str = ""
    channel: str = ""
    position: str = ""
    position_type: str = ""
    department: str = ""
    url: str = ""
    base_location: str = ""
    applied_date: date | None = None
    status: str = "待投递"
    current_stage: str = "投递"
    stage_result: str = "待处理"
    progress_updated_at: datetime | None = None
    referral_code: str = ""
    contact: str = ""
    interview_time: datetime | None = None
    result: str = ""
    notes: str = ""


class ApplicationPatch(BaseModel):
    company: str | None = None
    channel: str | None = None
    position: str | None = None
    position_type: str | None = None
    department: str | None = None
    url: str | None = None
    base_location: str | None = None
    applied_date: date | None = None
    status: str | None = None
    current_stage: str | None = None
    stage_result: str | None = None
    progress_updated_at: datetime | None = None
    referral_code: str | None = None
    contact: str | None = None
    interview_time: datetime | None = None
    result: str | None = None
    notes: str | None = None


class ApplicationOut(ApplicationInput):
    model_config = ConfigDict(from_attributes=True)
    id: int
    created_at: datetime


class ApplicationPage(BaseModel):
    items: list[ApplicationOut]
    total: int
    page: int
    page_size: int

