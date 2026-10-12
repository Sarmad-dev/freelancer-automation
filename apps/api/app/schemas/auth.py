from __future__ import annotations

import uuid
from typing import Annotated

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.schemas.text import Name


class SignUpRequest(BaseModel):
    email: EmailStr = Field(max_length=254)
    password: str = Field(max_length=128)
    display_name: Name


class SignInRequest(BaseModel):
    email: str = Field(min_length=1, max_length=254)
    # No complexity rules on sign-in: only the length cap that protects the hasher.
    password: str = Field(min_length=1, max_length=128)


class PasswordResetRequest(BaseModel):
    email: EmailStr = Field(max_length=254)


class PasswordResetConfirm(BaseModel):
    token: Annotated[str, Field(min_length=20, max_length=200)]
    password: str = Field(max_length=128)

    @field_validator("token")
    @classmethod
    def _token_chars(cls, v: str) -> str:
        if not all(c.isalnum() or c in "-_" for c in v):
            raise ValueError("Invalid token.")
        return v


class UserOut(BaseModel):
    id: uuid.UUID
    email: str
    display_name: str
    email_verified: bool


class WorkspaceOut(BaseModel):
    id: uuid.UUID
    name: str
    kind: str
    role: str
    timezone: str
    demo_mode: bool
    onboarding_status: str


class MeResponse(BaseModel):
    user: UserOut
    workspaces: list[WorkspaceOut]


class AuthConfig(BaseModel):
    password_reset_enabled: bool


class Accepted(BaseModel):
    status: str = "accepted"
