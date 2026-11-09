"""Pydantic models for the course contract (schemaVersion 1).

Two views of a course:

- ``CourseSource`` is the editing view. It comes from ``course.json`` and has no
  timing information.
- ``ResolvedCourse`` is the runtime view. It is produced by the resolver after
  merging the source with the root composition.

Both are strict: unknown fields are errors, because a silently ignored
``autoAdvence`` is worse than a build failure.
"""

from __future__ import annotations

import math
import re
from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
SCREEN_ID_PATTERN = re.compile(r"^[a-z][a-z0-9-]*$")
ACCENT_PATTERN = re.compile(r"^#[0-9a-fA-F]{6}$")
HEX_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")

Level = Literal["beginner", "intermediate", "advanced"]
Status = Literal["draft", "published", "archived"]
Playback = Literal["screens", "continuous"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


def _check_text(value: str, *, field: str, minimum: int, maximum: int) -> str:
    if not minimum <= len(value) <= maximum:
        raise ValueError(f"{field} 长度必须在 {minimum}–{maximum} 字符之间，当前 {len(value)}")
    return value


class SiteInfo(StrictModel):
    homeUrl: str | None = "/"
    backLabel: str = "返回课程库"

    @field_validator("homeUrl")
    @classmethod
    def _relative_or_absolute(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if value.startswith(("http://", "https://", "/")):
            return value
        raise ValueError("homeUrl 必须是绝对 URL、以 / 开头的站内路径，或 null")


class CreditsInfo(StrictModel):
    author: str | None = None
    updatedAt: str | None = None
    sources: list[str] = Field(default_factory=list)

    @field_validator("updatedAt")
    @classmethod
    def _date_format(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError("updatedAt 必须是 YYYY-MM-DD") from exc
        return value


class CompositionInfo(StrictModel):
    entry: str = "composition/index.html"
    width: Literal[1920] = 1920
    height: Literal[1080] = 1080
    fps: Literal[30] = 30

    @field_validator("entry")
    @classmethod
    def _entry_path(cls, value: str) -> str:
        if value.startswith("/") or ".." in value.split("/"):
            raise ValueError("entry 必须是 composition/ 下的相对路径")
        if not value.startswith("composition/") or not value.endswith(".html"):
            raise ValueError("entry 必须指向 composition/ 下的 .html 文件")
        return value


class ScreenMeta(StrictModel):
    id: str
    kicker: str | None = None
    title: str
    summary: str
    transcript: str | None = None
    autoAdvance: bool = False
    poster: str | None = None
    keywords: list[str] = Field(default_factory=list)

    @field_validator("id")
    @classmethod
    def _screen_id(cls, value: str) -> str:
        if not 1 <= len(value) <= 32 or not SCREEN_ID_PATTERN.match(value):
            raise ValueError("屏幕 id 必须匹配 ^[a-z][a-z0-9-]*$ 且为 1–32 个字符")
        return value

    @field_validator("title")
    @classmethod
    def _title(cls, value: str) -> str:
        return _check_text(value, field="screens[].title", minimum=1, maximum=40)

    @field_validator("summary")
    @classmethod
    def _summary(cls, value: str) -> str:
        return _check_text(value, field="screens[].summary", minimum=1, maximum=120)

    @field_validator("keywords")
    @classmethod
    def _keywords(cls, value: list[str]) -> list[str]:
        if len(value) > 5:
            raise ValueError("screens[].keywords 最多 5 个")
        return value


class CourseSource(StrictModel):
    schemaVersion: Literal[1]
    slug: str
    title: str
    subtitle: str | None = None
    summary: str
    description: str | None = None
    level: Level
    tags: list[str] = Field(default_factory=list)
    language: str = "zh-CN"
    status: Status
    featured: bool = False
    order: float = 100
    accent: str | None = None
    cover: str | None = None
    outcomes: list[str] = Field(default_factory=list)
    prerequisites: list[str] = Field(default_factory=list)
    takeaways: list[str] = Field(default_factory=list)
    audio: bool = False
    interactive: bool = False
    playback: Playback = "screens"
    composition: CompositionInfo = Field(default_factory=CompositionInfo)
    screens: list[ScreenMeta]
    site: SiteInfo = Field(default_factory=SiteInfo)
    credits: CreditsInfo = Field(default_factory=CreditsInfo)

    @field_validator("slug")
    @classmethod
    def _slug(cls, value: str) -> str:
        if not SLUG_PATTERN.match(value):
            raise ValueError("slug 必须匹配 ^[a-z0-9]+(?:-[a-z0-9]+)*$")
        return value

    @field_validator("title")
    @classmethod
    def _course_title(cls, value: str) -> str:
        return _check_text(value, field="title", minimum=2, maximum=40)

    @field_validator("subtitle")
    @classmethod
    def _subtitle(cls, value: str | None) -> str | None:
        if value is not None:
            _check_text(value, field="subtitle", minimum=1, maximum=60)
        return value

    @field_validator("summary")
    @classmethod
    def _course_summary(cls, value: str) -> str:
        return _check_text(value, field="summary", minimum=40, maximum=160)

    @field_validator("tags")
    @classmethod
    def _tags(cls, value: list[str]) -> list[str]:
        if len(value) > 5:
            raise ValueError("tags 最多 5 个")
        for tag in value:
            if len(tag) > 12:
                raise ValueError(f"tag {tag!r} 超过 12 个字符")
        return value

    @field_validator("accent")
    @classmethod
    def _accent(cls, value: str | None) -> str | None:
        if value is not None and not ACCENT_PATTERN.match(value):
            raise ValueError("accent 必须是 #RRGGBB 格式")
        return value

    @field_validator("cover")
    @classmethod
    def _cover(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if value.startswith("/") or ".." in value.split("/"):
            raise ValueError("cover 必须是课程目录内的相对路径")
        return value

    @field_validator("outcomes")
    @classmethod
    def _outcomes(cls, value: list[str]) -> list[str]:
        if value and not 2 <= len(value) <= 4:
            raise ValueError("outcomes 必须是 2–4 条")
        return value

    @field_validator("prerequisites")
    @classmethod
    def _prerequisites(cls, value: list[str]) -> list[str]:
        if len(value) > 3:
            raise ValueError("prerequisites 最多 3 条")
        return value

    @field_validator("takeaways")
    @classmethod
    def _takeaways(cls, value: list[str]) -> list[str]:
        if value and not 2 <= len(value) <= 4:
            raise ValueError("takeaways 必须是 2–4 条")
        return value

    @field_validator("screens")
    @classmethod
    def _screens(cls, value: list[ScreenMeta]) -> list[ScreenMeta]:
        if not value:
            raise ValueError("screens 至少需要 1 屏")
        seen: set[str] = set()
        for screen in value:
            if screen.id in seen:
                raise ValueError(f"屏幕 id 重复：{screen.id}")
            seen.add(screen.id)
        return value

    @model_validator(mode="after")
    def _audio_transcripts(self) -> CourseSource:
        if self.audio:
            missing = [screen.id for screen in self.screens if not screen.transcript]
            if missing:
                raise ValueError(f"audio=true 时每屏必须有 transcript；缺：{', '.join(missing)}")
        return self


class ResolvedScreen(ScreenMeta):
    index: int = Field(ge=0)
    start: float = Field(ge=0)
    duration: float = Field(gt=0)

    @field_validator("start", "duration")
    @classmethod
    def _finite(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("时间必须是有限数字")
        return value

    @property
    def end(self) -> float:
        return self.start + self.duration


class ResolvedComposition(CompositionInfo):
    duration: float = Field(gt=0)

    @field_validator("duration")
    @classmethod
    def _finite(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("composition.duration 必须是有限数字")
        return value


class CourseStats(StrictModel):
    screenCount: int = Field(ge=1)
    durationSeconds: float = Field(gt=0)
    estimatedMinutes: int = Field(ge=1)


class BuildInfo(StrictModel):
    runtimeVersion: str | None = None
    contentHash: str | None = None
    builtAt: str | None = None

    @field_validator("contentHash")
    @classmethod
    def _hash(cls, value: str | None) -> str | None:
        if value is not None and not HEX_SHA256_PATTERN.match(value):
            raise ValueError("contentHash 必须是 64 位小写十六进制")
        return value


class ResolvedCourse(CourseSource):
    composition: ResolvedComposition
    screens: list[ResolvedScreen]
    stats: CourseStats
    build: BuildInfo = Field(default_factory=BuildInfo)

    def to_summary(self, course_base_url: str = "/courses") -> CourseSummary:
        base = course_base_url.rstrip("/")
        return CourseSummary(
            slug=self.slug,
            title=self.title,
            subtitle=self.subtitle,
            summary=self.summary,
            level=self.level,
            tags=self.tags,
            language=self.language,
            status=self.status,
            featured=self.featured,
            order=self.order,
            accent=self.accent,
            coverUrl=f"{base}/{self.slug}/{self.cover}" if self.cover else None,
            courseUrl=f"{base}/{self.slug}/",
            screenCount=self.stats.screenCount,
            durationSeconds=self.stats.durationSeconds,
            estimatedMinutes=self.stats.estimatedMinutes,
            updatedAt=self.credits.updatedAt,
        )


class CourseSummary(StrictModel):
    slug: str
    title: str
    subtitle: str | None = None
    summary: str
    level: Level
    tags: list[str] = Field(default_factory=list)
    language: str = "zh-CN"
    status: Status = "published"
    featured: bool = False
    order: float = 100
    accent: str | None = None
    coverUrl: str | None = None
    courseUrl: str
    screenCount: int
    durationSeconds: float
    estimatedMinutes: int
    updatedAt: str | None = None


class CatalogError(StrictModel):
    code: str
    message: str
    slug: str | None = None
    file: str | None = None
    screen_id: str | None = None
    field: str | None = None
    expected: str | None = None


class CatalogStats(StrictModel):
    total: int = 0
    published: int = 0
    invalid: int = 0


class Catalog(BaseModel):
    model_config = ConfigDict(extra="forbid")

    courses: list[ResolvedCourse] = Field(default_factory=list)
    errors: list[CatalogError] = Field(default_factory=list)
    stats: CatalogStats = Field(default_factory=CatalogStats)

    def by_slug(self, slug: str) -> ResolvedCourse | None:
        return next((course for course in self.courses if course.slug == slug), None)

    def summaries(self, *, include_drafts: bool = True, course_base_url: str = "/courses") -> list[CourseSummary]:
        selected = [
            course
            for course in self.courses
            if include_drafts or course.status == "published"
        ]
        selected.sort(key=lambda course: (not course.featured, course.order, course.title))
        return [course.to_summary(course_base_url) for course in selected]
