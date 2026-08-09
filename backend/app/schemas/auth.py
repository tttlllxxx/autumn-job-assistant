from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str = Field(default="admin", max_length=100)
    password: str = Field(min_length=1, max_length=256)


class AuthResponse(BaseModel):
    authenticated: bool
    username: str = "admin"
    csrf_token: str | None = None

