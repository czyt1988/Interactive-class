"""Browser acceptance for an intro/outro clip inside a built course.

The build tests prove the composition gets the extra screens; this file proves
the shipped player treats them as ordinary chapters: the intro plays first, the
lesson numbering still starts at 01, the outro is last and "next" becomes 完成.
"""

from __future__ import annotations

import functools
import socket
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest

pytest.importorskip("playwright.sync_api")

from playwright.sync_api import Browser, Page, sync_playwright  # noqa: E402

from app.catalog.clips import ClipLibrary  # noqa: E402
from app.catalog.models import ClipSelection  # noqa: E402
from scripts.build_courses import build_all  # noqa: E402
from scripts.serve import CourseRequestHandler, ReusableTCPServer  # noqa: E402

FIXTURES = Path(__file__).parent.parent / "fixtures" / "courses"
CLIPS = Path(__file__).parent.parent.parent / "clips"
SLUG = "valid-two-screen"

pytestmark = pytest.mark.e2e


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture(scope="module")
def bundle(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("clips")
    results = build_all(
        source_root=FIXTURES,
        out_root=out,
        courses=[SLUG],
        clips={SLUG: ClipSelection(intro="intro-title-page", outro="outro-colophon")},
        clip_library=ClipLibrary(CLIPS),
    )
    assert results[0].ok, results[0].errors
    return out


@pytest.fixture(scope="module")
def server(bundle: Path) -> Iterator[tuple[str, int]]:
    port = _free_port()
    handler = functools.partial(CourseRequestHandler, directory=str(bundle / SLUG))
    httpd = ReusableTCPServer(("127.0.0.1", port), handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield "127.0.0.1", port
    finally:
        httpd.shutdown()


@pytest.fixture(scope="module")
def browser() -> Iterator[Browser]:
    with sync_playwright() as playwright:
        try:
            instance = playwright.chromium.launch(channel="chrome")
        except Exception:  # noqa: BLE001 - fall back to the bundled build
            try:
                instance = playwright.chromium.launch()
            except Exception as exc:  # noqa: BLE001
                pytest.skip(f"no Chromium available: {exc}")
        try:
            yield instance
        finally:
            instance.close()


@pytest.fixture
def page(browser: Browser, server: tuple[str, int]) -> Iterator[Page]:
    host, port = server
    context = browser.new_context(viewport={"width": 1280, "height": 900})
    page = context.new_page()
    page.console_errors = []  # type: ignore[attr-defined]
    page.external_requests = []  # type: ignore[attr-defined]
    page.on(
        "console",
        lambda message: page.console_errors.append(message.text)  # type: ignore[attr-defined]
        if message.type == "error"
        else None,
    )
    page.on(
        "request",
        lambda request: page.external_requests.append(request.url)  # type: ignore[attr-defined]
        if not request.url.startswith(f"http://{host}:{port}")
        else None,
    )
    page.goto(f"http://{host}:{port}/")
    yield page
    context.close()


def _start_playing(page: Page) -> None:
    page.click("#btn-start")
    page.wait_for_function("document.body.dataset.deckState === 'playing'", timeout=30_000)


def test_cover_lists_clips_without_renumbering_lessons(page: Page) -> None:
    assert page.locator(".outline__item").count() == 4
    labels = page.locator(".outline__num").all_inner_texts()
    assert labels == ["片头", "01", "02", "片尾"]
    assert page.locator("#deck-preview").is_hidden()
    assert page.console_errors == []
    assert page.external_requests == []


def test_intro_plays_first_then_lessons_start_at_01(page: Page) -> None:
    _start_playing(page)
    page.wait_for_timeout(400)
    assert page.inner_text("#chapter-title") == "片头：课程扉页"
    assert page.inner_text("#chapter-counter").startswith("片头")
    page.click("#btn-next")
    page.wait_for_function(
        "() => document.querySelector('#chapter-title').textContent === '第一屏'",
        timeout=15_000,
    )
    assert page.inner_text("#chapter-counter") == "01 / 04"
    assert page.console_errors == []
    assert page.external_requests == []


def test_outro_is_last_and_next_finishes(page: Page) -> None:
    _start_playing(page)
    page.click("#btn-toc")
    page.wait_for_selector("#toc:not([hidden])")
    page.locator(".toc__item").last.click()
    page.wait_for_function(
        "() => document.querySelector('#chapter-title').textContent === '片尾：项目落款'",
        timeout=15_000,
    )
    assert page.inner_text("#chapter-counter").startswith("片尾")
    assert page.inner_text("#btn-next .control__label") == "完成"
    page.click("#btn-next")
    page.wait_for_function("document.body.dataset.deckState === 'complete'", timeout=15_000)
    assert page.locator("#complete").is_visible()


def test_preview_query_opens_the_clip_in_the_classroom(
    page: Page, server: tuple[str, int]
) -> None:
    host, port = server
    page.goto(
        f"http://{host}:{port}/?preview=intro-title-page"
        "&back=/admin/courses/valid-two-screen/clips"
    )
    page.wait_for_function("document.body.dataset.deckState === 'playing'", timeout=30_000)
    assert page.inner_text("#chapter-title") == "片头：课程扉页"
    assert page.inner_text("#chapter-counter").startswith("片头")

    bar = page.locator("#deck-preview")
    assert bar.is_visible()
    assert page.get_attribute("#deck-preview-back", "href") == (
        "/admin/courses/valid-two-screen/clips"
    )
    assert page.inner_text("#deck-preview-kind") == "片头预览"
    assert page.evaluate("localStorage.getItem('ai-learning:progress:valid-two-screen')") is None

    # The preview stops on the clip's final frame instead of walking into the
    # course or opening the completion page.
    page.wait_for_function(
        "() => document.querySelector('#stage-wrap').classList.contains('is-ended')",
        timeout=25_000,
    )
    assert page.locator("#complete").is_hidden()
    assert page.inner_text("#deck-preview-kind") == "片头预览"
