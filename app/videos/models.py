"""Data models for on-demand course video rendering.

The JSON record written next to a video is deliberately separate from the
running job: the record survives a restart and tells the admin page whether the
last attempt succeeded, while the in-memory job only describes the current
process. Keeping the artifact and the last attempt apart means a failed
re-render does not hide a previously downloadable video.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

AttemptState = Literal["running", "succeeded", "failed", "interrupted"]
VideoState = Literal["missing", "running", "ready", "failed"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ArtifactRecord(StrictModel):
    generatedAt: str
    sizeBytes: int = Field(ge=1)
    durationSeconds: float = Field(gt=0)
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    quality: str
    contentHash: str | None = None


class AttemptRecord(StrictModel):
    status: AttemptState
    startedAt: str | None = None
    finishedAt: str | None = None
    message: str | None = None


class VideoRecord(StrictModel):
    schemaVersion: Literal[1] = 1
    slug: str
    artifact: ArtifactRecord | None = None
    lastAttempt: AttemptRecord | None = None


@dataclass(frozen=True)
class RenderRequest:
    """Everything one render needs; the manager owns the paths."""

    slug: str
    project_dir: Path
    output_path: Path
    log_path: Path
    quality: str
    timeout_seconds: int
    content_hash: str | None = None


@dataclass(frozen=True)
class RenderOutcome:
    size_bytes: int
    duration_seconds: float
    width: int
    height: int
    log_tail: tuple[str, ...] = ()


@dataclass(frozen=True)
class Artifact:
    """A rendered video as presented to the page."""

    path: Path
    size_bytes: int
    duration_seconds: float
    width: int
    height: int
    generated_at: str
    quality: str
    content_hash: str | None


@dataclass(frozen=True)
class JobView:
    state: str
    started_at: str | None
    elapsed_seconds: float
    message: str | None


@dataclass(frozen=True)
class VideoStatus:
    slug: str
    state: VideoState
    artifact: Artifact | None = None
    job: JobView | None = None
    message: str | None = None
    stale: bool = False

    @property
    def available(self) -> bool:
        return self.artifact is not None
