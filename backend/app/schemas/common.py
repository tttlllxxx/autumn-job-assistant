from typing import Any

from pydantic import BaseModel


class ApiError(BaseModel):
    code: str
    message: str
    recovery: str | None = None
    details: Any | None = None


class Page(BaseModel):
    items: list[Any]
    total: int
    page: int
    page_size: int

