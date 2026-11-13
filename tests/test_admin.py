"""Tests for the admin settings page and its video endpoints.

Real rendering needs a browser toolchain, so the app's render manager is
replaced with one that uses a fake runner. Environment discovery is patched too,
so these tests pass on any machine.
"""

from __future__ import annotations

import json
import re
import shutil
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.catalog import watermark as watermark_edit
from app.catalog import watermark_store
from app.catalog.models import Catalog, CatalogError
from app.config import Settings
from app.db import Base
from app.main import create_app
from app.videos.manager import RenderManager
from app.videos.models import RenderOutcome, RenderRequest
from app.videos.toolchain import EnvCheck, Toolchain
from app.web import admin as admin_module
from app.web.admin import ADMIN_COOKIE

SLUG = "valid-two-screen"
FAKE_MP4 = b"\x00\x00\x00\x18ftypmp42fake-video"
FIXTURE_COURSE = Path(__file__).parent / "fixtures" / "courses" / SLUG


def _toolchain(ok: bool = True) -> Toolchain:
    checks = tuple(
        EnvCheck(key=key, label=label, ok=ok, detail="已找到" if ok else "未找到")
        for key, label in (
            ("node", "Node.js"),
            ("hyperframes", "HyperFrames"),
            ("ffmpeg", "FFmpeg"),
            ("ffprobe", "FFprobe"),
        )
    )
    return Toolchain(
        node="node" if ok else None,
        cli=("node", "hyperframes.mjs") if ok else None,
        cli_label="测试用 CLI" if ok else "未找到",
        ffmpeg="ffmpeg" if ok else None,
        ffprobe="ffprobe" if ok else None,
        path_prefix=(),
        checks=checks,
    )


def _fake_runner(request: RenderRequest, on_line, stop_event) -> RenderOutcome:
    on_line("fake render")
    request.output_path.write_bytes(FAKE_MP4)
    return RenderOutcome(
        size_bytes=len(FAKE_MP4),
        duration_seconds=4.0,
        width=1920,
        height=1080,
    )


@dataclass
class Site:
    client: TestClient
    manager: RenderManager
    settings: Settings

    @property
    def catalog(self) -> Catalog:
        return self.client.app.state.catalog_loader.load(strict=False)


def _make_site(
    settings: Settings,
    write_course,
    monkeypatch,
    *,
    toolchain: Toolchain | None = None,
    with_source: bool = False,
) -> Site:
    write_course(settings.courses_dist_dir)
    if with_source:
        shutil.copytree(FIXTURE_COURSE, Path(settings.courses_src_dir) / SLUG)
    application = create_app(settings)
    Base.metadata.create_all(application.state.engine)
    manager = RenderManager(settings, runner=_fake_runner)
    application.state.video_manager = manager
    active = toolchain or _toolchain()
    monkeypatch.setattr(admin_module, "discover_toolchain", lambda _settings: active)
    client = TestClient(application)
    return Site(client=client, manager=manager, settings=settings)


def _wait_idle(manager: RenderManager, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not manager.is_busy():
            return
        time.sleep(0.01)
    raise AssertionError("render did not finish in time")


@pytest.fixture
def site(settings: Settings, write_course, monkeypatch) -> Iterator[Site]:
    made = _make_site(settings, write_course, monkeypatch)
    with made.client:
        yield made


@pytest.fixture
def source_site(settings: Settings, write_course, monkeypatch) -> Iterator[Site]:
    made = _make_site(settings, write_course, monkeypatch, with_source=True)
    with made.client:
        yield made


def test_admin_lists_courses_and_screen_counts(site: Site) -> None:
    response = site.client.get("/admin")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    text = response.text
    assert "两屏测试课" in text
    assert "2 屏" in text
    assert "未生成" in text
    assert f"/admin/videos/{SLUG}/render" in text
    assert "下载视频" not in text
    assert "后台没有设置访问密码" in text


def test_generate_then_download(site: Site) -> None:
    response = site.client.post(
        f"/admin/videos/{SLUG}/render", follow_redirects=False
    )
    assert response.status_code == 303
    assert "notice=started" in response.headers["location"]
    _wait_idle(site.manager)

    page = site.client.get("/admin")
    assert "已生成" in page.text
    assert "下载视频" in page.text

    download = site.client.get(f"/admin/videos/{SLUG}/download")
    assert download.status_code == 200
    assert download.content == FAKE_MP4
    assert download.headers["content-type"].startswith("video/mp4")
    assert "attachment" in download.headers["content-disposition"]
    assert "no-store" in download.headers["cache-control"]

    status = site.client.get("/admin/status").json()
    assert status["busy"] is False
    assert status["videos"][SLUG]["state"] == "ready"
    assert status["videos"][SLUG]["sizeBytes"] == len(FAKE_MP4)


def test_download_before_generation_is_404(site: Site) -> None:
    response = site.client.get(f"/admin/videos/{SLUG}/download")
    assert response.status_code == 404


def test_unknown_slug_redirects_with_notice(site: Site) -> None:
    response = site.client.post(
        "/admin/videos/does-not-exist/render", follow_redirects=False
    )
    assert response.status_code == 303
    assert "notice=notfound" in response.headers["location"]


def test_cross_site_post_is_rejected(site: Site) -> None:
    response = site.client.post(
        f"/admin/videos/{SLUG}/render",
        headers={"Origin": "https://evil.example"},
        follow_redirects=False,
    )
    assert response.status_code == 403


def test_unready_environment_disables_generation(
    settings: Settings, write_course, monkeypatch
) -> None:
    made = _make_site(settings, write_course, monkeypatch, toolchain=_toolchain(ok=False))
    with made.client:
        page = made.client.get("/admin")
        assert page.status_code == 200
        assert "未就绪" in page.text
        assert "生成环境未就绪" in page.text
        response = made.client.post(
            f"/admin/videos/{SLUG}/render", follow_redirects=False
        )
        assert response.status_code == 303
        assert "notice=unready" in response.headers["location"]


def test_admin_token_gate(settings: Settings, write_course, monkeypatch) -> None:
    protected = settings.model_copy(update={"admin_token": "s3cret"})
    write_course(protected.courses_dist_dir)
    application = create_app(protected)
    Base.metadata.create_all(application.state.engine)
    manager = RenderManager(protected, runner=_fake_runner)
    application.state.video_manager = manager
    monkeypatch.setattr(admin_module, "discover_toolchain", lambda _settings: _toolchain())

    with TestClient(application) as client:
        login_page = client.get("/admin")
        assert login_page.status_code == 401
        assert "输入管理密码" in login_page.text
        assert "两屏测试课" not in login_page.text

        blocked = client.post(
            f"/admin/videos/{SLUG}/render", follow_redirects=False
        )
        assert blocked.status_code == 303
        assert "notice=auth" in blocked.headers["location"]

        status = client.get("/admin/status")
        assert status.status_code == 401

        wrong = client.post("/admin/login", data={"token": "nope"})
        assert wrong.status_code == 401
        assert "管理密码不对" in wrong.text

        accepted = client.post(
            "/admin/login", data={"token": "s3cret"}, follow_redirects=False
        )
        assert accepted.status_code == 303
        assert ADMIN_COOKIE in accepted.cookies

        assert client.get("/admin").status_code == 200
        assert client.get("/admin/status").status_code == 200

        client.cookies.clear()
        assert client.get("/admin/status").status_code == 401
        header_auth = client.get(
            "/admin/status", headers={"X-Admin-Token": "s3cret"}
        )
        assert header_auth.status_code == 200


def test_robots_blocks_admin(site: Site) -> None:
    response = site.client.get("/robots.txt")
    assert response.status_code == 200
    assert "Disallow: /admin" in response.text


# -- watermark config ------------------------------------------------------


def _watermark_form(**overrides: str) -> dict[str, str]:
    data = {
        "action": "save",
        "enabled": "1",
        "corner_top_left_text": "作者：张三",
        "corner_top_left_fontSize": "30",
        "corner_top_left_color": "#16140f",
        "corner_top_left_opacity": "0.6",
        "corner_bottom_right_text": "示例公司",
        "corner_bottom_right_fontSize": "24",
        "corner_bottom_right_color": "#b8452b",
        "corner_bottom_right_opacity": "0.5",
        "repeat_text": "内部资料，请勿外传",
        "repeat_fontSize": "28",
        "repeat_color": "#16140f",
        "repeat_opacity": "0.12",
        "repeat_gapX": "320",
        "repeat_gapY": "200",
        "repeat_rotate": "-24",
    }
    data.update(overrides)
    return data


def _stored_watermark(site: Site):
    return watermark_store.load(site.settings, SLUG)


def _source_manifest(site: Site) -> dict:
    return json.loads(
        (Path(site.settings.courses_src_dir) / SLUG / "course.json").read_text(
            encoding="utf-8"
        )
    )


@pytest.fixture
def fake_rebuild(monkeypatch) -> list[str]:
    calls: list[str] = []

    def _rebuild(_settings: Settings, slug: str, watermark=None):
        calls.append(slug)
        return SimpleNamespace(errors=[], skipped=False)

    monkeypatch.setattr(watermark_edit, "rebuild_course", _rebuild)
    return calls


def test_admin_links_to_watermark_config(site: Site) -> None:
    page = site.client.get("/admin")
    assert page.status_code == 200
    assert f"/admin/courses/{SLUG}/watermark" in page.text
    assert "水印配置" in page.text
    assert "未配置水印" in page.text


def test_watermark_page_renders_form(source_site: Site) -> None:
    page = source_site.client.get(f"/admin/courses/{SLUG}/watermark")
    assert page.status_code == 200
    assert page.headers["cache-control"] == "no-store"
    assert "给《两屏测试课》加水印" in page.text
    assert "角标水印" in page.text
    assert "满屏平铺水印" in page.text
    assert 'name="corner_top_left_text"' in page.text
    assert 'name="repeat_text"' in page.text
    assert f'action="/admin/courses/{SLUG}/watermark"' in page.text
    # The config lives in the database; the source label only appears when this
    # machine cannot rebuild (the page explains it in that case).
    assert "course_watermarks" in page.text
    # The server-rendered preview must already cover the densest grid setting;
    # JavaScript only mirrors edits and does not add tiles.
    assert page.text.count("data-wm-tile") == watermark_edit.PREVIEW_TILES


def test_save_watermark_writes_to_database_and_redirects(
    source_site: Site, fake_rebuild: list[str]
) -> None:
    before = (Path(source_site.settings.courses_src_dir) / SLUG / "course.json").read_text(
        encoding="utf-8"
    )
    response = source_site.client.post(
        f"/admin/courses/{SLUG}/watermark",
        data=_watermark_form(),
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"].endswith("?notice=saved")
    assert fake_rebuild == [SLUG]

    # The watermark goes to the database, never into the course source.
    watermark = _stored_watermark(source_site)
    assert watermark is not None
    assert watermark.enabled is True
    assert [corner.position for corner in watermark.corners] == [
        "top-left",
        "bottom-right",
    ]
    assert watermark.repeating is not None
    assert watermark.repeating.text == "内部资料，请勿外传"
    assert (
        Path(source_site.settings.courses_src_dir) / SLUG / "course.json"
    ).read_text(encoding="utf-8") == before
    assert "watermark" not in _source_manifest(source_site)

    page = source_site.client.get(
        f"/admin/courses/{SLUG}/watermark?notice=saved"
    )
    assert "作者：张三" in page.text
    assert "水印已保存" in page.text


def test_invalid_watermark_is_reported_without_writing(
    source_site: Site, fake_rebuild: list[str]
) -> None:
    response = source_site.client.post(
        f"/admin/courses/{SLUG}/watermark",
        data=_watermark_form(corner_top_left_opacity="3"),
        follow_redirects=False,
    )
    assert response.status_code == 422
    assert "没有保存成功" in response.text
    assert "左上角透明度必须在 0 到 1 之间" in response.text
    assert "作者：张三" in response.text
    assert _stored_watermark(source_site) is None
    assert fake_rebuild == []


def test_clear_watermark_removes_the_row(
    source_site: Site, fake_rebuild: list[str]
) -> None:
    source_site.client.post(
        f"/admin/courses/{SLUG}/watermark", data=_watermark_form()
    )
    assert _stored_watermark(source_site) is not None

    response = source_site.client.post(
        f"/admin/courses/{SLUG}/watermark",
        data={"action": "clear"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"].endswith("?notice=cleared")
    assert _stored_watermark(source_site) is None
    assert fake_rebuild == [SLUG, SLUG]


def test_blank_save_clears_the_watermark_and_says_cleared(
    source_site: Site, fake_rebuild: list[str]
) -> None:
    source_site.client.post(
        f"/admin/courses/{SLUG}/watermark", data=_watermark_form()
    )
    assert _stored_watermark(source_site) is not None

    response = source_site.client.post(
        f"/admin/courses/{SLUG}/watermark",
        data={"action": "save", "enabled": "1"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"].endswith("?notice=cleared")
    assert _stored_watermark(source_site) is None


def test_watermark_rejects_non_form_posts(
    source_site: Site, fake_rebuild: list[str]
) -> None:
    source_site.client.post(
        f"/admin/courses/{SLUG}/watermark", data=_watermark_form()
    )
    response = source_site.client.post(
        f"/admin/courses/{SLUG}/watermark",
        json={"action": "save"},
        follow_redirects=False,
    )
    assert response.status_code == 415
    assert "只接受表单提交" in response.text
    assert _stored_watermark(source_site) is not None


def test_watermark_rejects_unknown_or_missing_action(
    source_site: Site, fake_rebuild: list[str]
) -> None:
    source_site.client.post(
        f"/admin/courses/{SLUG}/watermark", data=_watermark_form()
    )
    unknown_fields = source_site.client.post(
        f"/admin/courses/{SLUG}/watermark",
        data={"foo": "bar"},
        follow_redirects=False,
    )
    assert unknown_fields.status_code == 400
    assert "字段无法识别" in unknown_fields.text

    missing_action = source_site.client.post(
        f"/admin/courses/{SLUG}/watermark",
        data=_watermark_form(action=""),
        follow_redirects=False,
    )
    assert missing_action.status_code == 400
    assert "动作无法识别" in missing_action.text
    assert _stored_watermark(source_site) is not None


def test_watermark_page_is_read_only_without_source(site: Site) -> None:
    page = site.client.get(f"/admin/courses/{SLUG}/watermark")
    assert page.status_code == 200
    assert "没有" in page.text and "course.json" in page.text
    assert re.search(r'<button[^>]*value="save"[^>]*disabled', page.text)
    assert re.search(r'<button[^>]*value="clear"[^>]*disabled', page.text)

    response = site.client.post(
        f"/admin/courses/{SLUG}/watermark",
        data=_watermark_form(),
        follow_redirects=False,
    )
    assert response.status_code == 409
    assert "没有保存成功" in response.text
    assert not (Path(site.settings.courses_src_dir) / SLUG).exists()


def test_broken_source_saves_config_but_reports_build_failure(source_site: Site) -> None:
    manifest = Path(source_site.settings.courses_src_dir) / SLUG / "course.json"
    manifest.write_text("{broken json", encoding="utf-8")

    # The page is editable: the config lives in the database, not in this file.
    page = source_site.client.get(f"/admin/courses/{SLUG}/watermark")
    assert page.status_code == 200
    assert not re.search(r'<button[^>]*value="save"[^>]*disabled', page.text)

    response = source_site.client.post(
        f"/admin/courses/{SLUG}/watermark",
        data=_watermark_form(),
        follow_redirects=False,
    )
    assert response.status_code == 422
    assert "重新构建课程包失败" in response.text
    # The database write happens before the build; fixing the source and saving
    # again keeps the stored config.
    assert _stored_watermark(source_site) is not None
    assert manifest.read_text(encoding="utf-8") == "{broken json"


def test_watermark_rebuild_failure_is_reported(
    source_site: Site, monkeypatch
) -> None:
    def _failing(_settings: Settings, _slug: str, watermark=None):
        return SimpleNamespace(
            errors=[
                CatalogError(
                    code="manifest_invalid",
                    message="watermark.repeating.gapX 超出范围",
                    slug=SLUG,
                    field="watermark.repeating.gapX",
                )
            ],
            skipped=False,
        )

    monkeypatch.setattr(watermark_edit, "rebuild_course", _failing)
    response = source_site.client.post(
        f"/admin/courses/{SLUG}/watermark",
        data=_watermark_form(),
        follow_redirects=False,
    )
    assert response.status_code == 422
    assert "重新构建课程包失败" in response.text
    assert "manifest_invalid" in response.text
    assert _stored_watermark(source_site) is not None


def test_watermark_post_rejects_cross_site_origin(source_site: Site) -> None:
    response = source_site.client.post(
        f"/admin/courses/{SLUG}/watermark",
        data=_watermark_form(),
        headers={"Origin": "https://evil.example"},
        follow_redirects=False,
    )
    assert response.status_code == 403
    assert _stored_watermark(source_site) is None


def test_watermark_page_requires_admin_token(settings: Settings, write_course, monkeypatch) -> None:
    protected = settings.model_copy(update={"admin_token": "s3cret"})
    write_course(protected.courses_dist_dir)
    shutil.copytree(FIXTURE_COURSE, Path(protected.courses_src_dir) / SLUG)
    application = create_app(protected)
    Base.metadata.create_all(application.state.engine)
    monkeypatch.setattr(admin_module, "discover_toolchain", lambda _settings: _toolchain())

    with TestClient(application) as client:
        assert client.get(f"/admin/courses/{SLUG}/watermark").status_code == 401
        blocked = client.post(
            f"/admin/courses/{SLUG}/watermark",
            data=_watermark_form(),
            follow_redirects=False,
        )
        assert blocked.status_code == 303
        assert "notice=auth" in blocked.headers["location"]
        assert watermark_store.load(protected, SLUG) is None


def test_save_rebuilds_a_real_bundle(source_site: Site) -> None:
    response = source_site.client.post(
        f"/admin/courses/{SLUG}/watermark",
        data=_watermark_form(),
        follow_redirects=False,
    )
    assert response.status_code == 303, response.text
    # The watermark is baked into the built composition (the artifact both the
    # player and the MP4 renderer consume), not into the shell page.
    built = (
        Path(source_site.settings.courses_dist_dir)
        / SLUG
        / "composition"
        / "index.html"
    ).read_text(encoding="utf-8")
    assert "作者：张三" in built
    assert "内部资料，请勿外传" in built
    assert "course-watermark__corner--bottom-right" in built
    shell = (
        Path(source_site.settings.courses_dist_dir) / SLUG / "index.html"
    ).read_text(encoding="utf-8")
    assert "data-course-watermark" not in shell

    admin_page = source_site.client.get("/admin")
    assert "水印已配置" in admin_page.text
