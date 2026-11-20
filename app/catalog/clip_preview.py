"""Disposable classroom preview bundles for intro/outro templates.

The admin page needs to show a clip inside the real course page, not only as a
still. Saving the selection to preview it would change the live course, so a
preview builds a separate disposable bundle under ``data/clip-previews/`` with
exactly one clip selected. That bundle is a normal course page: same shell, same
player, same composition. It has progress sync disabled and the admin route
serves it behind the admin login; nothing in it is published or recorded.
"""

from __future__ import annotations

import re
import threading
from pathlib import Path

from app.catalog import watermark_store
from app.catalog.clips import ClipLibrary
from app.catalog.models import ClipKind, ClipSelection
from app.config import Settings

TOKEN_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,119}$")
# One preview build at a time. Two tabs of the same preview would otherwise race
# the staging-directory swap; the lock is separate from course rebuilds because
# these bundles live outside dist/ and never touch the database.
_PREVIEW_LOCK = threading.Lock()


def preview_root(settings: Settings) -> Path:
    return Path(settings.clip_preview_dir)


def token_for(slug: str, kind: ClipKind, clip_id: str) -> str:
    return f"{slug}-{kind}-{clip_id}"


def is_token(value: str) -> bool:
    return bool(TOKEN_RE.fullmatch(value))


def bundle_dir(settings: Settings, token: str, slug: str) -> Path:
    return preview_root(settings) / token / slug


def build(
    settings: Settings, slug: str, kind: ClipKind, clip_id: str
):
    """Build (or refresh) the preview bundle and return ``(token, result)``."""

    from scripts.build_courses import build_course

    token = token_for(slug, kind, clip_id)
    selection = ClipSelection(
        intro=clip_id if kind == "intro" else None,
        outro=clip_id if kind == "outro" else None,
    )
    with _PREVIEW_LOCK:
        result = build_course(
            Path(settings.courses_src_dir) / slug,
            out_root=preview_root(settings) / token,
            runtime_dir=Path(settings.runtime_dir),
            include_drafts=True,
            site_url=settings.site_url,
            site_title=settings.site_title,
            course_base_url=settings.course_base_url,
            # A preview must not write learner progress or call the progress API.
            progress_sync=False,
            watermark=watermark_store.load(settings, slug),
            clip_selection=selection,
            clip_library=ClipLibrary(Path(settings.clips_dir)),
            project_url=settings.project_url,
        )
    return token, result


def resolve_asset(settings: Settings, token: str, relative: str) -> Path | None:
    """Map a preview request path to a file, refusing to escape the token dir."""

    if not is_token(token):
        return None
    root = (preview_root(settings) / token).resolve()
    if not root.is_dir():
        return None
    cleaned = (relative or "index.html").lstrip("/")
    target = (root / cleaned).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        return None
    if target.is_dir():
        target = target / "index.html"
    return target if target.is_file() else None
