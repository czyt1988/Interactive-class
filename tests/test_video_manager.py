"""Tests for the on-demand video render manager.

The real renderer needs Chrome and FFmpeg, so these tests use a fake runner and
exercise the parts that can go wrong in production: job state, record files,
recovery after a restart, one render at a time, and keeping an old video when a
re-render fails.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest

from app.catalog.loader import load_catalog
from app.catalog.models import ResolvedCourse
from app.config import Settings
from app.videos.manager import (
    RenderBusy,
    RenderManager,
    RenderUnavailable,
    VideoLibrary,
)
from app.videos.models import (
    ArtifactRecord,
    AttemptRecord,
    RenderOutcome,
    RenderRequest,
    VideoRecord,
)
from app.videos.renderer import RenderFailed

SLUG = "valid-two-screen"
FAKE_MP4 = b"\x00\x00\x00\x18ftypmp42fake-video"


def _course(settings: Settings) -> ResolvedCourse:
    catalog = load_catalog(settings.courses_dist_dir, verify_bundles=True)
    course = catalog.by_slug(SLUG)
    assert course is not None
    return course


def _success_runner(payload: bytes = FAKE_MP4):
    def run(request: RenderRequest, on_line, stop_event) -> RenderOutcome:
        on_line("fake render")
        request.output_path.write_bytes(payload)
        return RenderOutcome(
            size_bytes=len(payload),
            duration_seconds=4.0,
            width=1920,
            height=1080,
        )

    return run


def _failing_runner(message: str = "渲染进程退出码 1。"):
    def run(request: RenderRequest, on_line, stop_event) -> RenderOutcome:
        on_line("fake failure")
        raise RenderFailed(message)

    return run


def _wait_idle(manager: RenderManager, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not manager.is_busy():
            return
        time.sleep(0.01)
    raise AssertionError("render did not finish in time")


def test_successful_render_records_artifact(settings: Settings, write_course) -> None:
    write_course(settings.courses_dist_dir)
    course = _course(settings)
    manager = RenderManager(settings, runner=_success_runner())
    manager.reconcile()
    try:
        job = manager.start(course)
        assert job.state == "running"
        _wait_idle(manager)

        status = manager.status(SLUG, content_hash=course.build.contentHash)
        assert status.state == "ready"
        assert status.artifact is not None
        assert status.artifact.path.read_bytes() == FAKE_MP4
        assert status.artifact.size_bytes == len(FAKE_MP4)

        record = json.loads(
            (settings.video_output_dir / f"{SLUG}.json").read_text(encoding="utf-8")
        )
        assert record["lastAttempt"]["status"] == "succeeded"
        assert record["artifact"]["sizeBytes"] == len(FAKE_MP4)
        assert record["artifact"]["width"] == 1920
        assert not list(settings.video_work_dir.glob("*"))
    finally:
        manager.close()


def test_failed_rerender_keeps_previous_video(settings: Settings, write_course) -> None:
    write_course(settings.courses_dist_dir)
    course = _course(settings)
    library = VideoLibrary(settings.video_output_dir)
    library.ensure_dir()
    library.video_path(SLUG).write_bytes(b"old-video")
    library.write(
        VideoRecord(
            slug=SLUG,
            artifact=ArtifactRecord(
                generatedAt="2026-01-01T00:00:00+00:00",
                sizeBytes=9,
                durationSeconds=4.0,
                width=1920,
                height=1080,
                quality="looks",
                contentHash="a" * 64,
            ),
            lastAttempt=AttemptRecord(
                status="succeeded", finishedAt="2026-01-01T00:00:00+00:00"
            ),
        )
    )

    manager = RenderManager(settings, library=library, runner=_failing_runner("boom"))
    try:
        manager.start(course)
        _wait_idle(manager)

        status = manager.status(SLUG, content_hash="b" * 64)
        assert status.state == "ready"
        assert status.artifact is not None
        assert status.artifact.path.read_bytes() == b"old-video"
        assert status.message == "boom"
        assert status.stale is True

        record = json.loads(
            (settings.video_output_dir / f"{SLUG}.json").read_text(encoding="utf-8")
        )
        assert record["lastAttempt"]["status"] == "failed"
        assert record["lastAttempt"]["message"] == "boom"
        assert record["artifact"]["contentHash"] == "a" * 64
    finally:
        manager.close()


def test_reconcile_marks_running_attempt_interrupted(
    settings: Settings, write_course
) -> None:
    write_course(settings.courses_dist_dir)
    library = VideoLibrary(settings.video_output_dir)
    library.ensure_dir()
    library.write(
        VideoRecord(
            slug=SLUG,
            lastAttempt=AttemptRecord(
                status="running", startedAt="2026-01-01T00:00:00+00:00"
            ),
        )
    )

    manager = RenderManager(settings, runner=_success_runner())
    try:
        manager.reconcile()
        record = VideoRecord.model_validate_json(
            (settings.video_output_dir / f"{SLUG}.json").read_text(encoding="utf-8")
        )
        assert record.lastAttempt is not None
        assert record.lastAttempt.status == "interrupted"
        assert record.lastAttempt.message
    finally:
        manager.close()


def test_only_one_render_runs_at_a_time(settings: Settings, write_course) -> None:
    write_course(settings.courses_dist_dir)
    course = _course(settings)
    gate = threading.Event()

    def blocking_runner(request: RenderRequest, on_line, stop_event) -> RenderOutcome:
        gate.wait(timeout=5)
        request.output_path.write_bytes(FAKE_MP4)
        return RenderOutcome(len(FAKE_MP4), 4.0, 1920, 1080)

    manager = RenderManager(settings, runner=blocking_runner)
    try:
        manager.start(course)
        with pytest.raises(RenderBusy):
            manager.start(course)
    finally:
        gate.set()
        _wait_idle(manager)
        manager.close()


def test_missing_composition_is_unavailable(settings: Settings, write_course) -> None:
    write_course(settings.courses_dist_dir)
    course = _course(settings)
    (settings.courses_dist_dir / SLUG / "composition" / "index.html").unlink()

    manager = RenderManager(settings, runner=_success_runner())
    try:
        assert manager.project_dir(course) is None
        with pytest.raises(RenderUnavailable):
            manager.start(course)
    finally:
        manager.close()


def test_status_missing_when_nothing_was_rendered(settings: Settings, write_course) -> None:
    write_course(settings.courses_dist_dir)
    manager = RenderManager(settings, runner=_success_runner())
    try:
        manager.reconcile()
        status = manager.status(SLUG)
        assert status.state == "missing"
        assert status.artifact is None
    finally:
        manager.close()
    assert Path(settings.video_work_dir).exists() is False or not list(
        Path(settings.video_work_dir).glob("*")
    )
