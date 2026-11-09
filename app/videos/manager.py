"""Single-job video rendering for the admin settings page.

The manager owns three pieces of state:

- the in-memory job (what is running in this process),
- the on-disk record written after every attempt,
- the rendered MP4 next to that record.

Only one render runs at a time. Each job copies the built composition into a
private work directory, so ``dist/`` stays untouched even when it is mounted
read-only, and a failed render cannot leave half-written files in the bundle
that learners load.
"""

from __future__ import annotations

import logging
import os
import shutil
import threading
import time
import uuid
from collections import deque
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError

from app.catalog.models import ResolvedCourse
from app.config import Settings
from app.formatting import format_duration
from app.videos.models import (
    Artifact,
    ArtifactRecord,
    AttemptRecord,
    AttemptState,
    JobView,
    RenderOutcome,
    RenderRequest,
    VideoRecord,
    VideoStatus,
)
from app.videos.renderer import (
    RenderCancelled,
    RenderError,
    RenderTimeout,
    RenderUnavailable,
    SubprocessRenderer,
)

logger = logging.getLogger(__name__)

Runner = Callable[[RenderRequest, Callable[[str], None], threading.Event], RenderOutcome]


class RenderBusy(RuntimeError):
    """Another video is already being rendered in this process."""


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _slug_ok(slug: str) -> bool:
    return bool(slug) and all(char.isalnum() or char in "-_" for char in slug)


class VideoLibrary:
    """The on-disk side: ``<slug>.mp4`` plus ``<slug>.json`` next to it."""

    def __init__(self, output_dir: Path) -> None:
        self.output_dir = output_dir

    def ensure_dir(self) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def video_path(self, slug: str) -> Path:
        return self.output_dir / f"{slug}.mp4"

    def record_path(self, slug: str) -> Path:
        return self.output_dir / f"{slug}.json"

    def failure_log_path(self, slug: str) -> Path:
        return self.output_dir / f"{slug}.render.log"

    def read(self, slug: str) -> VideoRecord | None:
        if not _slug_ok(slug):
            return None
        path = self.record_path(slug)
        try:
            raw = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None
        except OSError as exc:
            logger.warning("cannot read video record %s: %s", path, exc)
            return None
        try:
            record = VideoRecord.model_validate_json(raw)
        except ValidationError as exc:
            logger.warning("invalid video record %s: %s", path, exc)
            return None
        return record if record.slug == slug else None

    def records(self) -> list[VideoRecord]:
        if not self.output_dir.is_dir():
            return []
        found: list[VideoRecord] = []
        for path in sorted(self.output_dir.glob("*.json")):
            record = self.read(path.stem)
            if record is not None:
                found.append(record)
        return found

    def write(self, record: VideoRecord) -> None:
        self.ensure_dir()
        path = self.record_path(record.slug)
        temporary = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
        temporary.write_text(record.model_dump_json(indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, path)

    def start_attempt(self, slug: str, started_at: str) -> None:
        record = self.read(slug) or VideoRecord(slug=slug)
        record.lastAttempt = AttemptRecord(status="running", startedAt=started_at)
        self.write(record)

    def finish_attempt(
        self,
        slug: str,
        *,
        status: AttemptState,
        finished_at: str,
        message: str | None = None,
        artifact: ArtifactRecord | None = None,
    ) -> None:
        record = self.read(slug) or VideoRecord(slug=slug)
        started_at = record.lastAttempt.startedAt if record.lastAttempt else None
        if artifact is not None:
            record.artifact = artifact
        record.lastAttempt = AttemptRecord(
            status=status,
            startedAt=started_at,
            finishedAt=finished_at,
            message=message,
        )
        self.write(record)

    def artifact(self, slug: str) -> Artifact | None:
        record = self.read(slug)
        if record is None or record.artifact is None:
            return None
        path = self.video_path(slug)
        try:
            size = path.stat().st_size
        except OSError:
            return None
        info = record.artifact
        return Artifact(
            path=path,
            size_bytes=size,
            duration_seconds=info.durationSeconds,
            width=info.width,
            height=info.height,
            generated_at=info.generatedAt,
            quality=info.quality,
            content_hash=info.contentHash,
        )


@dataclass
class _Job:
    slug: str
    state: str = "running"
    started_at: str | None = None
    finished_at: str | None = None
    message: str | None = None
    stop: threading.Event = field(default_factory=threading.Event)
    log_tail: deque[str] = field(default_factory=lambda: deque(maxlen=20))


class RenderManager:
    def __init__(
        self,
        settings: Settings,
        *,
        library: VideoLibrary | None = None,
        runner: Runner | None = None,
    ) -> None:
        self.settings = settings
        self.library = library or VideoLibrary(settings.video_output_dir)
        self._runner = runner
        self._lock = threading.Lock()
        self._jobs: dict[str, _Job] = {}
        self._thread: threading.Thread | None = None
        self._closed = False

    # -- lifecycle ---------------------------------------------------------

    def reconcile(self) -> None:
        """Recover from a previous process that stopped mid-render."""

        try:
            self.library.ensure_dir()
        except OSError as exc:
            logger.warning("cannot create video output directory: %s", exc)
        self._clean_work_dir()
        for record in self.library.records():
            attempt = record.lastAttempt
            if attempt is None or attempt.status != "running":
                continue
            try:
                self.library.finish_attempt(
                    record.slug,
                    status="interrupted",
                    finished_at=_now_iso(),
                    message="服务重启，生成任务中断，请重新生成。",
                )
            except OSError as exc:
                logger.warning("cannot mark interrupted render %s: %s", record.slug, exc)

    def close(self) -> None:
        with self._lock:
            self._closed = True
            thread = self._thread
            for job in self._jobs.values():
                if job.state == "running":
                    job.stop.set()
        if thread is not None:
            thread.join(timeout=10)

    # -- queries -----------------------------------------------------------

    def is_busy(self) -> bool:
        with self._lock:
            return any(job.state == "running" for job in self._jobs.values())

    def status(self, slug: str, *, content_hash: str | None = None) -> VideoStatus:
        record = self.library.read(slug)
        artifact = self.library.artifact(slug)
        with self._lock:
            job = self._jobs.get(slug)
            job_view = self._job_view(job) if job is not None else None
            running = job is not None and job.state == "running"

        stale = bool(
            artifact
            and content_hash
            and artifact.content_hash
            and artifact.content_hash != content_hash
        )

        if running and job_view is not None:
            return VideoStatus(
                slug=slug,
                state="running",
                artifact=artifact,
                job=job_view,
                stale=stale,
            )

        message = job_view.message if job_view and job_view.state == "failed" else None
        if artifact is not None:
            if (
                message is None
                and record is not None
                and record.lastAttempt is not None
                and record.lastAttempt.status in {"failed", "interrupted"}
            ):
                message = record.lastAttempt.message
            return VideoStatus(
                slug=slug,
                state="ready",
                artifact=artifact,
                job=job_view,
                message=message,
                stale=stale,
            )

        if job_view is not None and job_view.state == "failed":
            return VideoStatus(slug=slug, state="failed", job=job_view, message=job_view.message)

        if record is not None:
            if record.lastAttempt is not None and record.lastAttempt.status in {
                "failed",
                "interrupted",
            }:
                return VideoStatus(
                    slug=slug,
                    state="failed",
                    message=record.lastAttempt.message,
                )
            if record.artifact is not None:
                return VideoStatus(
                    slug=slug,
                    state="failed",
                    message="记录显示已生成，但视频文件不存在，请重新生成。",
                )
        return VideoStatus(slug=slug, state="missing")

    # -- starting a render -------------------------------------------------

    def project_dir(self, course: ResolvedCourse) -> Path | None:
        course_dir = (self.settings.courses_dist_dir / course.slug).resolve()
        project = (course_dir / Path(course.composition.entry).parent).resolve()
        if not project.is_relative_to(course_dir):
            return None
        if not (project / "index.html").is_file():
            return None
        return project

    def start(self, course: ResolvedCourse) -> JobView:
        project = self.project_dir(course)
        if project is None:
            raise RenderUnavailable("服务器上找不到这门课的 composition，无法生成视频。")
        started_at = _now_iso()
        with self._lock:
            if self._closed:
                raise RenderUnavailable("服务正在关闭，请稍后再试。")
            if any(job.state == "running" for job in self._jobs.values()):
                raise RenderBusy("已有视频正在生成，等它完成后再试。")
            try:
                self.library.start_attempt(course.slug, started_at)
            except OSError as exc:
                raise RenderUnavailable(
                    "无法写入视频目录，请检查 VIDEO_OUTPUT_DIR 的权限。"
                ) from exc
            job = _Job(slug=course.slug, started_at=started_at)
            self._jobs[course.slug] = job
            thread = threading.Thread(
                target=self._run,
                args=(job, course, project),
                name=f"video-render-{course.slug}",
                daemon=True,
            )
            self._thread = thread
            thread.start()
            return self._job_view(job)

    # -- worker ------------------------------------------------------------

    def _run(self, job: _Job, course: ResolvedCourse, project_dir: Path) -> None:
        stamp = time.strftime("%Y%m%d-%H%M%S")
        work_dir = self.settings.video_work_dir / f"{course.slug}-{stamp}-{uuid.uuid4().hex[:8]}"
        log_path = work_dir / "render.log"
        state = "failed"
        message: str | None = "生成失败，请重试。"
        artifact: ArtifactRecord | None = None
        try:
            work_dir.mkdir(parents=True, exist_ok=True)
            project_copy = work_dir / "project"
            shutil.copytree(project_dir, project_copy)
            request = RenderRequest(
                slug=course.slug,
                project_dir=project_copy,
                output_path=work_dir / f"{course.slug}.mp4",
                log_path=log_path,
                quality=self.settings.video_quality,
                timeout_seconds=self.settings.video_render_timeout_seconds,
                content_hash=course.build.contentHash,
            )
            runner = self._runner or SubprocessRenderer(self.settings).run
            outcome = runner(request, self._on_line(job), job.stop)
            self.library.ensure_dir()
            os.replace(request.output_path, self.library.video_path(course.slug))
            artifact = ArtifactRecord(
                generatedAt=_now_iso(),
                sizeBytes=outcome.size_bytes,
                durationSeconds=outcome.duration_seconds,
                width=outcome.width,
                height=outcome.height,
                quality=self.settings.video_quality,
                contentHash=course.build.contentHash,
            )
            state = "succeeded"
            message = None
        except RenderCancelled:
            message = "生成已取消，服务正在关闭。"
        except RenderTimeout:
            message = (
                f"生成超时（超过 {format_duration(self.settings.video_render_timeout_seconds)}），"
                "可以稍后重试。"
            )
        except RenderUnavailable as exc:
            message = str(exc)
        except RenderError as exc:
            message = str(exc)
        except OSError:
            logger.exception("video render file operation failed: %s", course.slug)
            message = "文件读写失败，请检查视频目录和课程包是否完整。"
        except Exception:
            logger.exception("video render crashed: %s", course.slug)
            message = "生成失败，请查看服务器日志。"
        finally:
            finished_at = _now_iso()
            try:
                if state == "succeeded" and artifact is not None:
                    self.library.finish_attempt(
                        course.slug,
                        status="succeeded",
                        finished_at=finished_at,
                        artifact=artifact,
                    )
                    with suppress(OSError):
                        self.library.failure_log_path(course.slug).unlink()
                else:
                    self._keep_failure_log(course.slug, log_path)
                    self.library.finish_attempt(
                        course.slug,
                        status="failed",
                        finished_at=finished_at,
                        message=message,
                    )
            except OSError:
                logger.exception("cannot persist video record: %s", course.slug)
            shutil.rmtree(work_dir, ignore_errors=True)
            with self._lock:
                job.state = state
                job.finished_at = finished_at
                job.message = message
                self._thread = None

    # -- helpers -----------------------------------------------------------

    def _job_view(self, job: _Job) -> JobView:
        elapsed = 0.0
        if job.started_at:
            try:
                started = datetime.fromisoformat(job.started_at)
            except ValueError:
                started = None
            if started is not None:
                elapsed = max(0.0, (datetime.now(UTC) - started).total_seconds())
        return JobView(
            state=job.state,
            started_at=job.started_at,
            elapsed_seconds=elapsed,
            message=job.message,
        )

    def _on_line(self, job: _Job) -> Callable[[str], None]:
        def record(line: str) -> None:
            text = line.strip()
            if not text:
                return
            with self._lock:
                job.log_tail.append(text[:300])

        return record

    def _keep_failure_log(self, slug: str, log_path: Path) -> None:
        try:
            if not log_path.is_file():
                return
            self.library.ensure_dir()
            target = self.library.failure_log_path(slug)
            temporary = target.with_name(f".{target.name}.tmp")
            shutil.copyfile(log_path, temporary)
            os.replace(temporary, target)
        except OSError:
            logger.warning("cannot keep render log for %s", slug, exc_info=True)

    def _clean_work_dir(self) -> None:
        work_dir = self.settings.video_work_dir
        try:
            if not work_dir.is_dir():
                return
            for child in work_dir.iterdir():
                if child.is_dir():
                    shutil.rmtree(child, ignore_errors=True)
                else:
                    with suppress(OSError):
                        child.unlink()
        except OSError as exc:
            logger.warning("cannot clean video work directory: %s", exc)
