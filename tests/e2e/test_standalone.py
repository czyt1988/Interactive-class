"""Standalone bundle acceptance: a course must play on a plain static server.

No FastAPI, no database, no login. This is the hard gate from the architecture
doc (9.5): if it fails, the course cannot ship.
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

from scripts.build_courses import build_all  # noqa: E402
from scripts.serve import CourseRequestHandler, ReusableTCPServer  # noqa: E402

FIXTURES = Path(__file__).parent.parent / "fixtures" / "courses"
SLUG = "valid-two-screen"

pytestmark = pytest.mark.e2e


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture(scope="module")
def bundle(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("standalone")
    results = build_all(source_root=FIXTURES, out_root=out, courses=[SLUG])
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
        and not request.url.startswith("data:")
        else None,
    )
    page.goto(f"http://{host}:{port}/", wait_until="load")
    page.wait_for_function("document.body.dataset.deckReady === 'true'", timeout=25_000)
    yield page
    context.close()


def test_cover_renders_without_script_errors(page: Page) -> None:
    assert "两屏测试课" in page.title()
    assert page.locator("#cover").is_visible()
    assert page.locator(".outline__item").count() == 2
    assert page.console_errors == []


def test_start_plays_first_screen(page: Page) -> None:
    page.click("#btn-start")
    page.wait_for_function("document.body.dataset.deckState === 'playing'", timeout=25_000)
    page.wait_for_timeout(1200)
    assert page.inner_text("#chapter-title") == "第一屏"
    assert page.get_attribute("#btn-play", "aria-pressed") == "true"


def test_ended_fires_at_range_end(page: Page) -> None:
    page.click("#btn-start")
    page.wait_for_function("document.body.dataset.deckState === 'playing'", timeout=25_000)
    # The fixture screen is 2 s long; the natural range end must fire `ended`.
    page.wait_for_function(
        "() => document.querySelector('#stage-wrap').classList.contains('is-ended')",
        timeout=15_000,
    )
    current = page.evaluate("() => document.querySelector('#hf-player').currentTime")
    assert 1.5 <= current <= 2.6


def test_next_and_prev_switch_screens(page: Page) -> None:
    page.click("#btn-start")
    page.wait_for_function("document.body.dataset.deckState === 'playing'", timeout=25_000)
    page.click("#btn-next")
    page.wait_for_function(
        "() => document.querySelector('#chapter-title').textContent === '第二屏'", timeout=15_000
    )
    page.click("#btn-prev")
    page.wait_for_function(
        "() => document.querySelector('#chapter-title').textContent === '第一屏'", timeout=15_000
    )


def test_transcript_opens_with_text(page: Page) -> None:
    page.click("#btn-start")
    page.wait_for_function("document.body.dataset.deckState === 'playing'", timeout=25_000)
    page.click("#btn-transcript")
    page.wait_for_selector("#transcript:not([hidden])")
    assert page.inner_text("#transcript-body").strip()
    page.keyboard.press("Escape")
    page.wait_for_selector("#transcript[hidden]", state="attached", timeout=5_000)


def test_deep_link_opens_paused_on_that_screen(page: Page) -> None:
    # A hash-only goto is a same-document navigation, so the deck would not boot
    # again; reload to simulate opening a shared deep link in a fresh tab.
    page.goto(page.url.split("#")[0] + "#s=split", wait_until="load")
    page.reload(wait_until="load")
    page.wait_for_function("document.body.dataset.deckReady === 'true'", timeout=25_000)
    assert page.locator("#deck-deep-hint").is_visible()
    assert page.evaluate("() => document.body.dataset.deckState") == "cover"


def test_standalone_bundle_makes_no_external_requests(page: Page) -> None:
    page.click("#btn-start")
    page.wait_for_function("document.body.dataset.deckState === 'playing'", timeout=25_000)
    page.wait_for_timeout(1500)
    assert page.external_requests == []
    assert page.console_errors == []


def test_local_progress_survives_reload(page: Page) -> None:
    page.click("#btn-start")
    page.wait_for_function("document.body.dataset.deckState === 'playing'", timeout=25_000)
    page.click("#btn-next")
    page.wait_for_function(
        "() => document.querySelector('#chapter-title').textContent === '第二屏'", timeout=15_000
    )
    page.reload(wait_until="load")
    page.wait_for_function("document.body.dataset.deckReady === 'true'", timeout=25_000)
    assert page.locator("#btn-resume").is_visible()
