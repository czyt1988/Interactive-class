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
# Open-source project address printed by the shipped intro template. Override
# with PROJECT_URL when a fork or a deployment lives somewhere else.
DEFAULT_PROJECT_URL = "https://gitee.com/czyt1988/interactive-class"


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

    # Shared intro/outro clip library (``clips/<clip-id>/``). A clip is one more
    # scene injected at build time; the selection per course lives in SQLite, not
    # in the course source. This URL is printed by the shipped intro template and
    # identifies the open-source project, so it is deployment config as well.
    clips_dir: Path = Field(default=BASE_DIR / "clips")
    project_url: str = DEFAULT_PROJECT_URL

    strict_catalog: bool | None = None
    include_drafts: bool | None = None
    verify_course_bundles: bool = True
    session_cookie_secure: bool | None = None
    session_cookie_days: int = 180
    progress_max_body_bytes: int = 4096

    # Admin page and on-demand video rendering. The site still serves courses
    # without any of this; rendering only runs when someone asks for it.
    admin_token: str | None = None
    video_output_dir: Path = Field(default=BASE_DIR / "data" / "videos")
    video_work_dir: Path = Field(default=BASE_DIR / "data" / "videos" / ".work")
    video_quality: Literal["draft", "looks", "delivery"] = "looks"
    video_render_timeout_seconds: int = Field(default=7200, ge=60, le=86400)
    video_hyperframes_cli: Path | None = None
    video_hyperframes_version: str = Field(default="0.9.19", pattern=r"^\d+\.\d+\.\d+$")
    video_node_bin: str = "node"
    video_npx_bin: str = "npx"
    video_ffmpeg_dir: Path | None = None

    # Course import page (authoring convenience, dev-only by default). Importing
    # copies an external course folder into ``courses/``, builds it and records
    # provenance in SQLite; the catalog still reads only ``dist/``.
    courses_inbox_dir: Path = Field(default=BASE_DIR / "course-inbox")
    course_import_enabled: bool | None = None

    @field_validator(
        "courses_src_dir",
        "courses_dist_dir",
        "runtime_dir",
        "design_dir",
        "clips_dir",
        "video_output_dir",
        "video_work_dir",
        "courses_inbox_dir",
    )
    @classmethod
    def _absolute_path(cls, value: Path) -> Path:
        return value if value.is_absolute() else (BASE_DIR / value).resolve()

    @field_validator("project_url")
    @classmethod
    def _project_url(cls, value: str) -> str:
        url = value.strip().rstrip("/")
        if not url.startswith(("http://", "https://")):
            raise ValueError("PROJECT_URL 必须是 http:// 或 https:// 开头的地址")
        return url

    @field_validator("video_hyperframes_cli", "video_ffmpeg_dir", mode="before")
    @classmethod
    def _optional_path(cls, value: object) -> Path | None:
        if value is None or (isinstance(value, str) and not value.strip()):
            return None
        if isinstance(value, Path):
            return value if value.is_absolute() else (BASE_DIR / value).resolve()
        if isinstance(value, str):
            path = Path(value.strip())
            return path if path.is_absolute() else (BASE_DIR / path).resolve()
        raise ValueError("路径必须是字符串或 Path")

    @field_validator("admin_token", mode="before")
    @classmethod
    def _blank_token_is_none(cls, value: object) -> str | None:
        if value is None:
            return None
        if isinstance(value, str):
            stripped = value.strip()
            return stripped or None
        raise ValueError("ADMIN_TOKEN 必须是字符串")

    @model_validator(mode="after")
    def _environment_defaults(self) -> Settings:
        prod = self.env == "prod"
        if self.strict_catalog is None:
            self.strict_catalog = prod
        if self.include_drafts is None:
            self.include_drafts = not prod
        if self.session_cookie_secure is None:
            self.session_cookie_secure = prod
        if self.course_import_enabled is None:
            self.course_import_enabled = not prod
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
