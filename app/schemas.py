"""Request and response models for the progress API."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ProgressUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    screenId: str = Field(min_length=1, max_length=32, pattern=r"^[a-z][a-z0-9-]*$")
    completed: bool = True


class ProgressResponse(BaseModel):
    lastScreenId: str | None = None
    completedScreens: list[str] = Field(default_factory=list)
    updatedAt: datetime | None = None


class CourseProgressResponse(ProgressResponse):
    courseSlug: str
    completed: bool = False


class AllProgressResponse(BaseModel):
    courses: list[CourseProgressResponse] = Field(default_factory=list)


class ErrorBody(BaseModel):
    code: str
    message: str
    details: dict[str, object] = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    error: ErrorBody
