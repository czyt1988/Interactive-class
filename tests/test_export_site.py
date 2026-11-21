from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from app.config import Settings
from app.web.routes import site_context
from scripts.export_site import (
    ExportError,
    check_output,
    export_site,
    load_publish_clips,
    normalise_base_path,
)

FIXTURES = Path(__file__).parent / "fixtures" / "courses"
SLUG = "valid-two-screen"
SITE_URL = "https://example.github.io"
BASE_PATH = "/demo"


@pytest.fixture
def source_dir(tmp_path: Path) -> Path:
    target = tmp_path / "courses"
    shutil.copytree(FIXTURES / SLUG, target / SLUG)
    return target


def test_export_is_self_contained_and_prefixed(
    tmp_path: Path, source_dir: Path
) -> None:
    output = tmp_path / "site"
    report = export_site(
        site_url=SITE_URL,
        base_path=BASE_PATH,
        output=output,
        source_root=source_dir,
        publish_config=None,
    )

    for relative in (
        "index.html",
        "courses/index.html",
        "about/index.html",
        "404.html",
        "sitemap.xml",
        "robots.txt",
        ".nojekyll",
        "static/site.css",
        "static/site.js",
        f"courses/{SLUG}/index.html",
        f"courses/{SLUG}/course.json",
    ):
        assert (output / relative).is_file(), relative

    assert report.courses == 1
    assert report.screens == 2
    assert report.base_path == BASE_PATH

    home = (output / "index.html").read_text(encoding="utf-8")
    assert f'href="{BASE_PATH}/courses/{SLUG}/"' in home
    assert 'href="/static' not in home
    assert "/admin" not in home
    assert "127.0.0.1" not in home

    library = (output / "courses/index.html").read_text(encoding="utf-8")
    assert "data-catalog-static" in library
    assert f'href="{BASE_PATH}/courses?level=beginner"' in library

    course = (output / f"courses/{SLUG}/index.html").read_text(encoding="utf-8")
    # The course manifest says homeUrl "/", which the export makes "/demo/".
    assert f'href="{BASE_PATH}/"' in course
    assert "/api/progress" not in course

    not_found = (output / "404.html").read_text(encoding="utf-8")
    assert 'rel="canonical"' not in not_found
    assert f'href="{BASE_PATH}/"' in not_found

    sitemap = (output / "sitemap.xml").read_text(encoding="utf-8")
    assert f"<loc>{SITE_URL}{BASE_PATH}/courses/{SLUG}/</loc>" in sitemap

    robots = (output / "robots.txt").read_text(encoding="utf-8")
    assert f"Sitemap: {SITE_URL}{BASE_PATH}/sitemap.xml" in robots
    assert f"Disallow: {BASE_PATH}/admin" in robots


def test_export_applies_publish_clips(tmp_path: Path, source_dir: Path) -> None:
    config = tmp_path / "publish.json"
    config.write_text(
        json.dumps({"clips": {SLUG: {"intro": "intro-title-page"}}}, ensure_ascii=False),
        encoding="utf-8",
    )

    output = tmp_path / "site"
    report = export_site(
        site_url=SITE_URL,
        base_path=BASE_PATH,
        output=output,
        source_root=source_dir,
        publish_config=config,
    )

    assert report.screens == 3
    course = json.loads(
        (output / f"courses/{SLUG}/course.json").read_text(encoding="utf-8")
    )
    assert course["screens"][0]["kind"] == "intro"


def test_export_rejects_a_broken_base_path(tmp_path: Path, source_dir: Path) -> None:
    with pytest.raises(ExportError):
        export_site(
            site_url=SITE_URL,
            base_path="//demo",
            output=tmp_path / "site",
            source_root=source_dir,
            publish_config=None,
        )


def test_check_output_flags_a_missing_file(tmp_path: Path) -> None:
    output = tmp_path / "site"
    output.mkdir()
    (output / "index.html").write_text('<a href="/demo/about">关于</a>', encoding="utf-8")

    problems = check_output(output, site_url=SITE_URL, base_path=BASE_PATH)

    assert any("about" in problem and "不存在" in problem for problem in problems)


def test_check_output_flags_a_missing_base_path(tmp_path: Path) -> None:
    output = tmp_path / "site"
    output.mkdir()
    (output / "index.html").write_text('<a href="/about">关于</a>', encoding="utf-8")

    problems = check_output(output, site_url=SITE_URL, base_path=BASE_PATH)

    assert any("子路径" in problem for problem in problems)


def test_check_output_flags_a_localhost_leak(tmp_path: Path) -> None:
    output = tmp_path / "site"
    output.mkdir()
    (output / "index.html").write_text(
        '<a href="http://127.0.0.1:8081/about">关于</a>', encoding="utf-8"
    )

    problems = check_output(output, site_url=SITE_URL, base_path="")

    assert any("本机地址" in problem for problem in problems)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("", ""), ("/repo", "/repo"), ("/repo/", "/repo"), ("/a/b", "/a/b")],
)
def test_normalise_base_path(raw: str, expected: str) -> None:
    assert normalise_base_path(raw) == expected


@pytest.mark.parametrize("raw", ["repo", "//repo", "/a//b", "/a/../b"])
def test_normalise_base_path_rejects_bad_values(raw: str) -> None:
    with pytest.raises(ExportError):
        normalise_base_path(raw)


def test_load_publish_clips_reads_the_committed_selection(tmp_path: Path) -> None:
    config = tmp_path / "publish.json"
    config.write_text(
        json.dumps({"clips": {SLUG: {"intro": "intro-title-page", "outro": None}}}),
        encoding="utf-8",
    )

    clips = load_publish_clips(config)

    assert clips[SLUG].intro == "intro-title-page"
    assert clips[SLUG].outro is None
    assert load_publish_clips(None) == {}
    assert load_publish_clips(tmp_path / "missing.json") == {}


def test_load_publish_clips_rejects_unknown_fields(tmp_path: Path) -> None:
    config = tmp_path / "publish.json"
    config.write_text(json.dumps({"watermarks": {}}), encoding="utf-8")

    with pytest.raises(ExportError):
        load_publish_clips(config)


def test_site_context_prefixes_links_and_derives_course_base_url() -> None:
    settings = Settings(env="dev", site_base_path="/demo/", database_url="sqlite://")
    context = site_context(settings)

    assert settings.site_base_path == "/demo"
    assert settings.course_base_url == "/demo/courses"
    assert context["link"]("/courses") == "/demo/courses"
    assert context["link"]("/") == "/demo/"
    assert context["admin"] is True
    assert context["static"] is False


def test_static_export_hides_the_admin_entry() -> None:
    settings = Settings(
        env="prod", site_base_path="/demo", static_export=True, database_url="sqlite://"
    )
    context = site_context(settings)

    assert context["admin"] is False
    assert context["static"] is True
