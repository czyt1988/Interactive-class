from __future__ import annotations

import functools
import http.server
import json
import shutil
import socketserver
import threading
from pathlib import Path

import pytest

from scripts.build_courses import build_all, build_course, discover_courses

FIXTURES = Path(__file__).parent / "fixtures" / "courses"
SLUG = "valid-two-screen"


@pytest.fixture
def source_dir(tmp_path: Path) -> Path:
    target = tmp_path / "courses"
    shutil.copytree(FIXTURES / SLUG, target / SLUG)
    return target


def test_build_copies_bundle(tmp_path: Path, source_dir: Path) -> None:
    out = tmp_path / "dist"
    results = build_all(source_root=source_dir, out_root=out, courses=[SLUG])
    assert len(results) == 1 and results[0].ok
    bundle = out / SLUG
    for relative in (
        "index.html",
        "course.json",
        "composition/index.html",
        "composition/compositions/01-hook.html",
        "runtime/course-deck.js",
        "runtime/course-deck.css",
        "runtime/vendor/hyperframes-player.global.js",
        "runtime/vendor/hyperframe.runtime.iife.js",
    ):
        assert (bundle / relative).is_file(), relative


def test_build_excludes_authoring_files(tmp_path: Path, source_dir: Path) -> None:
    (source_dir / SLUG / "STORYBOARD.md").write_text("# board", encoding="utf-8")
    (source_dir / SLUG / "composition" / "package.json").write_text("{}", encoding="utf-8")
    (source_dir / SLUG / "composition" / "hyperframes.json").write_text("{}", encoding="utf-8")
    (source_dir / SLUG / "composition" / "node_modules").mkdir()
    (source_dir / SLUG / "composition" / "node_modules" / "x.js").write_text("//", encoding="utf-8")
    # Per-run snapshot/review caches are gitignored and can be large; they must
    # never be copied into the bundle or counted against its budget.
    (source_dir / SLUG / "composition" / ".snaps-review").mkdir()
    (source_dir / SLUG / "composition" / ".snaps-review" / "frame.png").write_bytes(b"x" * 4096)
    (source_dir / SLUG / "composition" / ".review-2026-11").mkdir()
    (source_dir / SLUG / "composition" / ".review-2026-11" / "frame.png").write_bytes(b"x" * 4096)

    build_all(source_root=source_dir, out_root=tmp_path / "dist", courses=[SLUG])
    bundle = tmp_path / "dist" / SLUG
    assert not (bundle / "STORYBOARD.md").exists()
    assert not (bundle / "composition" / "package.json").exists()
    assert not (bundle / "composition" / "hyperframes.json").exists()
    assert not (bundle / "composition" / "node_modules").exists()
    assert not (bundle / "composition" / ".snaps-review").exists()
    assert not (bundle / "composition" / ".review-2026-11").exists()
    assert not (bundle / "runtime" / "shell.html.j2").exists()


def test_resolved_manifest_has_timing(tmp_path: Path, source_dir: Path) -> None:
    build_all(source_root=source_dir, out_root=tmp_path / "dist", courses=[SLUG])
    manifest = json.loads((tmp_path / "dist" / SLUG / "course.json").read_text(encoding="utf-8"))
    assert manifest["stats"]["screenCount"] == 2
    assert [screen["start"] for screen in manifest["screens"]] == [0, 2]
    assert [screen["duration"] for screen in manifest["screens"]] == [2, 2]
    assert manifest["composition"]["duration"] == 4
    assert manifest["build"]["contentHash"]


def test_shell_points_at_local_runtime(tmp_path: Path, source_dir: Path) -> None:
    build_all(source_root=source_dir, out_root=tmp_path / "dist", courses=[SLUG])
    html = (tmp_path / "dist" / SLUG / "index.html").read_text(encoding="utf-8")
    assert 'runtime-src="./runtime/vendor/hyperframe.runtime.iife.js"' in html
    assert "./runtime/vendor/hyperframes-player.global.js" in html
    assert "./composition/index.html" not in html  # src is set by the deck at start
    assert "http://" not in html.replace("http://127.0.0.1:8000", "")
    assert 'id="course-data"' in html


def test_build_is_idempotent(tmp_path: Path, source_dir: Path) -> None:
    first = build_course(source_dir / SLUG, out_root=tmp_path / "dist")
    second = build_course(source_dir / SLUG, out_root=tmp_path / "dist")
    assert first.content_hash == second.content_hash


def test_external_asset_is_rejected(tmp_path: Path, source_dir: Path) -> None:
    scene = source_dir / SLUG / "composition" / "compositions" / "01-hook.html"
    scene.write_text(
        scene.read_text(encoding="utf-8").replace(
            "gsap.timeline", "gsap.timeline"
        )
        + "\n<!-- <link rel=\"stylesheet\" href=\"https://fonts.googleapis.com/css2?family=X\" /> -->\n",
        encoding="utf-8",
    )
    # A comment is not a resource load; put a real one in the root composition.
    index = source_dir / SLUG / "composition" / "index.html"
    index.write_text(
        index.read_text(encoding="utf-8").replace(
            "<body>",
            '<body>\n<script src="https://cdn.example.com/evil.js"></script>',
        ),
        encoding="utf-8",
    )
    result = build_course(source_dir / SLUG, out_root=tmp_path / "dist")
    codes = {error.code for error in result.errors}
    assert "external_asset" in codes
    assert not (tmp_path / "dist" / SLUG / "index.html").exists()


def test_missing_vendor_is_rejected(tmp_path: Path, source_dir: Path) -> None:
    (source_dir / SLUG / "composition" / "assets" / "vendor" / "gsap.min.js").unlink()
    result = build_course(source_dir / SLUG, out_root=tmp_path / "dist")
    codes = {error.code for error in result.errors}
    assert "vendor_missing" in codes


def test_drafts_are_skipped_by_default(tmp_path: Path, source_dir: Path) -> None:
    manifest_path = source_dir / SLUG / "course.json"
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload["status"] = "draft"
    manifest_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    skipped = build_course(source_dir / SLUG, out_root=tmp_path / "dist")
    assert skipped.skipped and not skipped.errors

    built = build_course(source_dir / SLUG, out_root=tmp_path / "dist", include_drafts=True)
    assert built.ok and built.screens == 2


def test_check_only_writes_nothing(tmp_path: Path, source_dir: Path) -> None:
    result = build_course(source_dir / SLUG, out_root=tmp_path / "dist", check_only=True)
    assert result.ok
    assert not (tmp_path / "dist").exists()


def test_discover_skips_private_dirs(tmp_path: Path, source_dir: Path) -> None:
    (source_dir / "_template").mkdir()
    (source_dir / ".hidden").mkdir()
    names = [path.name for path in discover_courses(source_dir)]
    assert names == [SLUG]


def test_bundle_is_served_by_a_plain_static_server(tmp_path: Path, source_dir: Path) -> None:
    import urllib.request

    build_all(source_root=source_dir, out_root=tmp_path / "dist", courses=[SLUG])
    bundle = tmp_path / "dist" / SLUG

    handler = functools.partial(
        http.server.SimpleHTTPRequestHandler, directory=str(bundle)
    )

    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *_args):  # noqa: ANN002
            pass

    handler = functools.partial(Quiet, directory=str(bundle))
    with socketserver.TCPServer(("127.0.0.1", 0), handler) as server:
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            for relative in ("index.html", "composition/index.html", "course.json", "runtime/course-deck.js"):
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/{relative}") as response:
                    assert response.status == 200
        finally:
            server.shutdown()
