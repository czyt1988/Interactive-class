"""Tests for the intro/outro clip library, build injection, storage and admin page.

The contract these tests pin: a clip is one more scene of the course composition,
injected at build time (so playback and the MP4 agree), selected per course in
the site database (never in ``course.json``), and unable to introduce external
resources.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.catalog import clip_store
from app.catalog.clips import (
    ClipBuildError,
    ClipContext,
    ClipDefinition,
    ClipLibrary,
    build_context,
    clip_frame_html,
    render_scene,
    title_size,
)
from app.catalog.models import ClipSelection
from app.catalog.resolver import resolve_course
from app.config import Settings
from app.db import Base
from app.main import create_app
from scripts.build_courses import build_all, build_course

FIXTURES = Path(__file__).parent / "fixtures" / "courses"
SLUG = "valid-two-screen"
CLIPS = Path(__file__).parent.parent / "clips"


def _settings(tmp_path: Path, *, clips_dir: Path = CLIPS) -> Settings:
    return Settings(
        env="dev",
        courses_src_dir=tmp_path / "courses",
        courses_dist_dir=tmp_path / "dist" / "courses",
        clips_dir=clips_dir,
        project_url="https://gitee.com/czyt1988/interactive-class",
        database_url=f"sqlite:///{(tmp_path / 'test.db').as_posix()}",
        include_drafts=True,
        verify_course_bundles=True,
        video_output_dir=tmp_path / "data" / "videos",
        video_work_dir=tmp_path / "data" / "videos" / ".work",
    )


def _source(tmp_path: Path) -> Path:
    root = tmp_path / "courses"
    shutil.copytree(FIXTURES / SLUG, root / SLUG)
    return root / SLUG


def _context(tmp_path: Path, **overrides: str):
    source = _source(tmp_path)
    course = resolve_course(source)
    return build_context(
        course,
        site_title=overrides.get("site_title", "AI Learning"),
        project_url=overrides.get(
            "project_url", "https://gitee.com/czyt1988/interactive-class"
        ),
        course_url=overrides.get("course_url", "http://127.0.0.1:8000/courses/valid-two-screen/"),
    )


# -- library ---------------------------------------------------------------


def test_shipped_library_has_one_intro_and_one_outro() -> None:
    library = ClipLibrary(CLIPS)
    assert [clip.id for clip in library.for_kind("intro")] == ["intro-title-page"]
    assert [clip.id for clip in library.for_kind("outro")] == ["outro-colophon"]
    assert library.issues() == []


def test_broken_clip_is_reported_not_listed(tmp_path: Path) -> None:
    root = tmp_path / "clips"
    broken = root / "intro-broken"
    broken.mkdir(parents=True)
    (broken / "clip.json").write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "id": "intro-broken",
                "kind": "intro",
                "title": "坏片头",
                "summary": "缺少时间轴",
                "duration": 10,
            }
        ),
        encoding="utf-8",
    )
    (broken / "scene.html").write_text(
        '<template><div id="root"></div></template>', encoding="utf-8"
    )
    library = ClipLibrary(root)
    assert library.definitions() == []
    codes = {issue.code for issue in library.issues()}
    assert "clip_scene_invalid" in codes


def test_clip_with_external_asset_is_rejected(tmp_path: Path) -> None:
    root = tmp_path / "clips"
    clip = root / "intro-external"
    clip.mkdir(parents=True)
    (clip / "clip.json").write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "id": "intro-external",
                "kind": "intro",
                "title": "外链片头",
                "summary": "引用了外部图片",
                "duration": 10,
            }
        ),
        encoding="utf-8",
    )
    (clip / "scene.html").write_text(
        """<template>
  <style>#root { opacity: 1; }</style>
  <div id="root" data-composition-id="s-intro-external">
    <img src="https://example.com/logo.png" alt="" />
  </div>
  <script>window.__timelines["s-intro-external"] = gsap.timeline({ paused: true });</script>
</template>""",
        encoding="utf-8",
    )
    library = ClipLibrary(root)
    assert library.definitions() == []
    messages = " ".join(issue.message for issue in library.issues())
    assert "自包含" in messages


def test_clip_id_must_match_folder_and_kind() -> None:
    payload = {
        "schemaVersion": 1,
        "id": "intro-x",
        "kind": "outro",
        "title": "方向不对",
        "summary": "kind 与 id 前缀不一致",
        "duration": 10,
    }
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="outro"):
        ClipDefinition.model_validate(payload)


# -- placeholders ----------------------------------------------------------


def test_placeholders_are_filled_and_escaped(tmp_path: Path) -> None:
    context = _context(tmp_path)
    rendered = render_scene(
        "<h1>{{ course.title }}</h1><span>{{ project.label }}</span>",
        context,
        clip_id="intro-title-page",
    )
    assert "两屏测试课" in rendered
    assert "gitee.com/czyt1988/interactive-class" in rendered

    escaped = render_scene(
        "<p>{{ course.title }}</p>",
        ClipContext({"course.title": "<b>标题</b>"}),
        clip_id="intro-title-page",
    )
    assert escaped == "<p>&lt;b&gt;标题&lt;/b&gt;</p>"

    with pytest.raises(ClipBuildError) as caught:
        render_scene("{{ course.unknown }}", context, clip_id="intro-title-page")
    assert caught.value.errors[0].code == "clip_placeholder_unknown"


def test_title_size_fits_long_titles() -> None:
    sizes = [title_size("短标题"), title_size("二" * 20), title_size("三" * 40)]
    assert sizes[0] > sizes[1] > sizes[2]
    # Two lines at the chosen size must stay inside the 1536px title zone.
    for length, size in ((12, title_size("a" * 12)), (40, title_size("a" * 40))):
        assert -(-length // (1536 // size)) <= 2


# -- build injection -------------------------------------------------------


def test_build_injects_both_clips(tmp_path: Path) -> None:
    out = tmp_path / "dist"
    source = _source(tmp_path)
    result = build_course(
        source,
        out_root=out,
        clip_selection=ClipSelection(intro="intro-title-page", outro="outro-colophon"),
        clip_library=ClipLibrary(CLIPS),
        project_url="https://gitee.com/czyt1988/interactive-class",
    )
    assert result.ok, result.errors
    assert result.screens == 4
    assert result.duration == 23

    bundle = out / SLUG
    manifest = json.loads((bundle / "course.json").read_text(encoding="utf-8"))
    assert [(screen["id"], screen["kind"]) for screen in manifest["screens"]] == [
        ("intro-title-page", "intro"),
        ("hook", "lesson"),
        ("split", "lesson"),
        ("outro-colophon", "outro"),
    ]
    assert [screen["start"] for screen in manifest["screens"]] == [0, 10, 12, 14]
    assert manifest["composition"]["duration"] == 23
    assert manifest["stats"]["screenCount"] == 4
    assert manifest["stats"]["durationSeconds"] == 23

    root = (bundle / "composition" / "index.html").read_text(encoding="utf-8")
    assert 'data-duration="23"' in root
    assert 'data-screen-id="intro-title-page"' in root
    assert 'data-screen-id="outro-colophon"' in root
    assert root.count("data-screen-id=") == 4
    assert 'data-start="10"' in root and 'data-start="12"' in root and 'data-start="14"' in root
    assert "compositions/clip-intro-title-page.html" in root
    assert (bundle / "composition" / "compositions" / "clip-intro-title-page.html").is_file()
    assert (bundle / "composition" / "compositions" / "clip-outro-colophon.html").is_file()

    scene = (bundle / "composition" / "compositions" / "clip-intro-title-page.html").read_text(
        encoding="utf-8"
    )
    assert "两屏测试课" in scene
    assert "gitee.com/czyt1988/interactive-class" in scene
    assert "DeepSeek Harness" in scene


def test_shell_labels_clips_as_intro_and_outro(tmp_path: Path) -> None:
    out = tmp_path / "dist"
    build_course(
        _source(tmp_path),
        out_root=out,
        clip_selection=ClipSelection(intro="intro-title-page", outro="outro-colophon"),
        clip_library=ClipLibrary(CLIPS),
    )
    html = (out / SLUG / "index.html").read_text(encoding="utf-8")
    assert html.count('class="toc__item"') == 4
    assert 'data-screen-kind="intro"' in html
    assert 'data-screen-kind="outro"' in html
    assert "片头" in html and "片尾" in html
    # Lesson numbers stay 01/02 even though two clip rows precede/close them.
    assert '<span class="outline__num">01</span>' in html
    assert '<span class="outline__num">02</span>' in html
    assert '<span class="toc__num">01</span>' in html
    # The last row is the outro, so the deck can label "next" as 完成.
    assert "toc__item" in html


def test_no_selection_builds_byte_identical_root(tmp_path: Path) -> None:
    plain = tmp_path / "plain"
    with_clips_dir = tmp_path / "with"
    source = _source(tmp_path)
    first = build_course(source, out_root=plain, clip_library=ClipLibrary(CLIPS))
    second = build_course(
        source,
        out_root=with_clips_dir,
        clip_selection=None,
        clip_library=ClipLibrary(CLIPS),
    )
    assert first.ok and second.ok
    plain_root = (plain / SLUG / "composition" / "index.html").read_bytes()
    other_root = (with_clips_dir / SLUG / "composition" / "index.html").read_bytes()
    assert plain_root == other_root
    manifest = json.loads((with_clips_dir / SLUG / "course.json").read_text(encoding="utf-8"))
    assert all(screen["kind"] == "lesson" for screen in manifest["screens"])
    assert first.content_hash == second.content_hash


def test_intro_only_and_outro_only_timings(tmp_path: Path) -> None:
    intro_out = tmp_path / "intro"
    build_course(
        _source(tmp_path / "intro-source"),
        out_root=intro_out,
        clip_selection=ClipSelection(intro="intro-title-page"),
        clip_library=ClipLibrary(CLIPS),
    )
    intro_manifest = json.loads(
        (intro_out / SLUG / "course.json").read_text(encoding="utf-8")
    )
    assert [(s["id"], s["start"]) for s in intro_manifest["screens"]] == [
        ("intro-title-page", 0),
        ("hook", 10),
        ("split", 12),
    ]
    assert intro_manifest["composition"]["duration"] == 14
    intro_root = (intro_out / SLUG / "composition" / "index.html").read_text(encoding="utf-8")
    assert "outro-colophon" not in intro_root

    outro_out = tmp_path / "outro"
    build_course(
        _source(tmp_path / "outro-source"),
        out_root=outro_out,
        clip_selection=ClipSelection(outro="outro-colophon"),
        clip_library=ClipLibrary(CLIPS),
    )
    outro_manifest = json.loads(
        (outro_out / SLUG / "course.json").read_text(encoding="utf-8")
    )
    assert [(s["id"], s["start"]) for s in outro_manifest["screens"]] == [
        ("hook", 0),
        ("split", 2),
        ("outro-colophon", 4),
    ]
    assert outro_manifest["composition"]["duration"] == 13
    outro_root = (outro_out / SLUG / "composition" / "index.html").read_text(encoding="utf-8")
    assert "intro-title-page" not in outro_root


def test_content_hash_changes_with_clip_selection(tmp_path: Path) -> None:
    source = _source(tmp_path)
    plain = build_course(source, out_root=tmp_path / "a", clip_library=ClipLibrary(CLIPS))
    with_intro = build_course(
        source,
        out_root=tmp_path / "b",
        clip_selection=ClipSelection(intro="intro-title-page"),
        clip_library=ClipLibrary(CLIPS),
    )
    with_outro = build_course(
        source,
        out_root=tmp_path / "c",
        clip_selection=ClipSelection(outro="outro-colophon"),
        clip_library=ClipLibrary(CLIPS),
    )
    assert len({plain.content_hash, with_intro.content_hash, with_outro.content_hash}) == 3


def test_check_only_validates_clips_without_writing(tmp_path: Path) -> None:
    result = build_course(
        _source(tmp_path),
        out_root=tmp_path / "dist",
        check_only=True,
        clip_selection=ClipSelection(intro="intro-title-page"),
        clip_library=ClipLibrary(CLIPS),
    )
    assert result.ok
    assert result.screens == 3
    assert not (tmp_path / "dist").exists()


def test_missing_clip_is_a_build_error(tmp_path: Path) -> None:
    result = build_course(
        _source(tmp_path),
        out_root=tmp_path / "dist",
        clip_selection=ClipSelection(intro="intro-does-not-exist"),
        clip_library=ClipLibrary(CLIPS),
    )
    assert not result.ok
    assert "clip_missing" in {error.code for error in result.errors}


def test_wrong_kind_is_a_build_error(tmp_path: Path) -> None:
    result = build_course(
        _source(tmp_path),
        out_root=tmp_path / "dist",
        clip_selection=ClipSelection(intro="outro-colophon"),
        clip_library=ClipLibrary(CLIPS),
    )
    assert not result.ok
    assert "clip_kind_mismatch" in {error.code for error in result.errors}


def test_clip_id_collision_is_a_build_error(tmp_path: Path) -> None:
    source = _source(tmp_path)
    # Rename the first course screen to the clip id: the host, manifest and scene
    # all have to agree before the resolver accepts the course.
    manifest_path = source / "course.json"
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload["screens"][0]["id"] = "intro-title-page"
    manifest_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    for path in (
        source / "composition" / "index.html",
        source / "composition" / "compositions" / "01-hook.html",
    ):
        text = path.read_text(encoding="utf-8").replace("s-hook", "s-intro-title-page")
        text = text.replace('data-screen-id="hook"', 'data-screen-id="intro-title-page"')
        path.write_text(text, encoding="utf-8")
    result = build_course(
        source,
        out_root=tmp_path / "dist",
        clip_selection=ClipSelection(intro="intro-title-page"),
        clip_library=ClipLibrary(CLIPS),
    )
    assert not result.ok
    assert "clip_screen_collision" in {error.code for error in result.errors}


# -- storage ---------------------------------------------------------------


def _create_tables(settings: Settings) -> None:
    from app.db import create_db_engine

    engine = create_db_engine(settings.database_url)
    Base.metadata.create_all(engine)
    engine.dispose()


def test_clip_selection_round_trips(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    _create_tables(settings)
    selection = ClipSelection(intro="intro-title-page", outro="outro-colophon")
    clip_store.save(settings, SLUG, selection)
    assert clip_store.load(settings, SLUG) == selection
    assert clip_store.load_all(settings) == {SLUG: selection}

    clip_store.save(settings, SLUG, ClipSelection(intro="intro-title-page"))
    assert clip_store.load(settings, SLUG).intro == "intro-title-page"
    assert clip_store.load(settings, SLUG).outro is None

    clip_store.save(settings, SLUG, None)
    assert clip_store.load(settings, SLUG) is None
    assert clip_store.load_all(settings) == {}


def test_clip_store_forgives_missing_table(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    assert clip_store.load(settings, SLUG) is None
    assert clip_store.load_all(settings) == {}


def test_clip_selection_rejects_bad_slug() -> None:
    with pytest.raises(ValueError, match="id"):
        ClipSelection(intro="Not A Clip")


# -- admin -----------------------------------------------------------------


def _admin_site(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    settings = _settings(tmp_path)
    source = _source(tmp_path)
    results = build_all(
        source_root=settings.courses_src_dir,
        out_root=settings.courses_dist_dir,
        courses=[SLUG],
        clip_library=ClipLibrary(settings.clips_dir),
        project_url=settings.project_url,
    )
    assert results[0].ok, results[0].errors
    application = create_app(settings)
    Base.metadata.create_all(application.state.engine)
    client = TestClient(application)
    return client, settings, source


def test_admin_clips_page_lists_templates(tmp_path: Path, monkeypatch) -> None:
    client, settings, _source_dir = _admin_site(tmp_path, monkeypatch)
    with client:
        response = client.get(f"/admin/courses/{SLUG}/clips")
    assert response.status_code == 200
    text = response.text
    assert "片头片尾" in text
    assert "片头：课程扉页" in text
    assert "片尾：项目落款" in text
    assert "/admin/clips/intro-title-page/frame?course=valid-two-screen" in text


def test_admin_saves_and_rebuilds_with_clips(tmp_path: Path, monkeypatch) -> None:
    client, settings, source = _admin_site(tmp_path, monkeypatch)
    with client:
        response = client.post(
            f"/admin/courses/{SLUG}/clips",
            data={
                "action": "save",
                "intro": "intro-title-page",
                "outro": "outro-colophon",
            },
            headers={"content-type": "application/x-www-form-urlencoded"},
            follow_redirects=False,
        )
        assert response.status_code == 303
        assert response.headers["location"].endswith("?notice=saved")
        saved = clip_store.load(settings, SLUG)
        assert saved == ClipSelection(intro="intro-title-page", outro="outro-colophon")

        manifest = json.loads(
            (settings.courses_dist_dir / SLUG / "course.json").read_text(encoding="utf-8")
        )
        assert [(screen["id"], screen["kind"]) for screen in manifest["screens"]] == [
            ("intro-title-page", "intro"),
            ("hook", "lesson"),
            ("split", "lesson"),
            ("outro-colophon", "outro"),
        ]
        # The course page the admin page rebuilt is immediately servable.
        assert client.get(f"/courses/{SLUG}/").status_code == 200
        assert "片头" in client.get(f"/courses/{SLUG}/").text


def test_admin_clear_removes_clips(tmp_path: Path, monkeypatch) -> None:
    client, settings, _source_dir = _admin_site(tmp_path, monkeypatch)
    with client:
        client.post(
            f"/admin/courses/{SLUG}/clips",
            data={"action": "save", "intro": "intro-title-page", "outro": ""},
            headers={"content-type": "application/x-www-form-urlencoded"},
            follow_redirects=False,
        )
        assert clip_store.load(settings, SLUG) is not None
        response = client.post(
            f"/admin/courses/{SLUG}/clips",
            data={"action": "clear", "intro": "", "outro": ""},
            headers={"content-type": "application/x-www-form-urlencoded"},
            follow_redirects=False,
        )
        assert response.status_code == 303
        assert clip_store.load(settings, SLUG) is None
        manifest = json.loads(
            (settings.courses_dist_dir / SLUG / "course.json").read_text(encoding="utf-8")
        )
        assert all(screen["kind"] == "lesson" for screen in manifest["screens"])


def test_admin_rejects_unknown_or_mistyped_clip(tmp_path: Path, monkeypatch) -> None:
    client, settings, _source_dir = _admin_site(tmp_path, monkeypatch)
    with client:
        unknown = client.post(
            f"/admin/courses/{SLUG}/clips",
            data={"action": "save", "intro": "intro-nope", "outro": ""},
            headers={"content-type": "application/x-www-form-urlencoded"},
            follow_redirects=False,
        )
        assert unknown.status_code == 422
        wrong_kind = client.post(
            f"/admin/courses/{SLUG}/clips",
            data={"action": "save", "intro": "outro-colophon", "outro": ""},
            headers={"content-type": "application/x-www-form-urlencoded"},
            follow_redirects=False,
        )
        assert wrong_kind.status_code == 422
        assert clip_store.load(settings, SLUG) is None


def test_admin_frame_renders_the_clip_for_the_course(tmp_path: Path, monkeypatch) -> None:
    client, _settings_, _source_dir = _admin_site(tmp_path, monkeypatch)
    with client:
        response = client.get("/admin/clips/intro-title-page/frame?course=valid-two-screen")
        assert response.status_code == 200
        assert "两屏测试课" in response.text
        assert "gitee.com/czyt1988/interactive-class" in response.text
        assert "script-src 'self'" in response.headers["content-security-policy"]
        missing = client.get("/admin/clips/intro-nope/frame?course=valid-two-screen")
        assert missing.status_code == 404


def test_frame_html_reveals_the_final_layout(tmp_path: Path) -> None:
    library = ClipLibrary(CLIPS)
    clip = library.get("intro-title-page")
    assert clip is not None
    context = _context(tmp_path)
    html_doc = clip_frame_html(
        clip, library.scene_path(clip).read_text(encoding="utf-8"), context
    )
    assert "opacity: 1 !important" in html_doc
    assert "<script" in html_doc
    assert "/static/clip_frame.js" in html_doc
    assert "s-intro-title-page" in html_doc
