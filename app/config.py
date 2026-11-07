"""Application configuration.

Environment variables are read through ``pydantic-settings``. Paths are resolved
against the repository root so the app behaves the same no matter which
directory ``uvicorn`` is started from.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    env: Literal["dev", "prod"] = "dev"
    site_title: str = "AI Learning"
    site_url: str = "http://127.0.0.1:8000"
    course_base_url: str = "/courses"

    courses_src_dir: Path = Field(default=BASE_DIR / "courses")
    courses_dist_dir: Path = Field(default=BASE_DIR / "dist" / "courses")
    runtime_dir: Path = Field(default=BASE_DIR / "runtime")
    design_dir: Path = Field(default=BASE_DIR / "design")
    database_url: str = "sqlite:///./data/app.db"

    strict_catalog: bool | None = None
    include_drafts: bool | None = None
    verify_course_bundles: bool = True
    session_cookie_secure: bool | None = None
    session_cookie_days: int = 180
    progress_max_body_bytes: int = 4096

    @field_validator("courses_src_dir", "courses_dist_dir", "runtime_dir", "design_dir")
    @classmethod
    def _absolute_path(cls, value: Path) -> Path:
        return value if value.is_absolute() else (BASE_DIR / value).resolve()

    @model_validator(mode="after")
    def _environment_defaults(self) -> Settings:
        prod = self.env == "prod"
        if self.strict_catalog is None:
            self.strict_catalog = prod
        if self.include_drafts is None:
            self.include_drafts = not prod
        if self.session_cookie_secure is None:
            self.session_cookie_secure = prod
        if self.database_url.startswith("sqlite:///./"):
            relative = self.database_url.removeprefix("sqlite:///./")
            self.database_url = f"sqlite:///{(BASE_DIR / relative).as_posix()}"
        return self

    @property
    def is_prod(self) -> bool:
        return self.env == "prod"


@lru_cache
def get_settings() -> Settings:
    return Settings()
