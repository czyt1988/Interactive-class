"""Standalone bundle acceptance: a course must play on a plain static server.

No FastAPI, no database, no login. This is the hard gate from the architecture
doc (9.5): if it fails, the course cannot ship.
"""

from __future__ import annotations

import functools
import re
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


def _rgb(value: str) -> tuple[float, float, float]:
    """Accept rgb()/rgba()/color(srgb ...), which color-mix() produces."""

    srgb = re.search(r"color\(srgb ([0-9.]+) ([0-9.]+) ([0-9.]+)", value)
    if srgb:
        return tuple(float(part) * 255 for part in srgb.groups())  # type: ignore[return-value]
    legacy = re.search(r"rgba?\(([0-9.]+), ([0-9.]+), ([0-9.]+)", value)
    assert legacy, f"unrecognised colour: {value}"
    return tuple(float(part) for part in legacy.groups())  # type: ignore[return-value]


def _luminance(value: str) -> float:
    channels = []
    for raw in _rgb(value):
        channel = raw / 255
        channels.append(channel / 12.92 if channel <= 0.03928 else ((channel + 0.055) / 1.055) ** 2.4)
    red, green, blue = channels
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def test_deck_shell_is_light_not_dark(page: Page) -> None:
    """The user asked for the course to be light; the deck must not be a dark app."""

    assert page.locator('meta[name="color-scheme"]').get_attribute("content") == "light"
    body_background = page.evaluate("() => getComputedStyle(document.body).backgroundColor")
    assert _luminance(body_background) > 0.7, body_background
    bar_background = page.evaluate("() => getComputedStyle(document.querySelector('.deck-bar')).backgroundColor")
    assert _luminance(bar_background) > 0.6, bar_background


def test_exit_control_ends_viewing_and_returns_to_library(page: Page) -> None:
    # Not reachable from the cover; it appears with the stage control bar.
    assert not page.locator("#btn-exit").is_visible()

    page.click("#btn-start")
    page.wait_for_function("document.body.dataset.deckState === 'playing'", timeout=25_000)

    assert page.locator(".controls > *").first.get_attribute("id") == "btn-exit"

    exit_link = page.locator("#btn-exit")
    assert exit_link.is_visible()
    assert exit_link.get_attribute("href") == "/"
    assert "返回课程库" in (exit_link.get_attribute("aria-label") or "")

    with page.expect_navigation(wait_until="load", timeout=15_000):
        exit_link.click()
    page.wait_for_function("document.body.dataset.deckReady === 'true'", timeout=25_000)
    assert page.evaluate("() => location.pathname") == "/"
    # A fresh document, not the deck mid-play: the cover is showing again.
    assert page.evaluate("() => document.body.dataset.deckState") == "cover"


def _start_playing(page: Page) -> None:
    page.click("#btn-start")
    page.wait_for_function("document.body.dataset.deckState === 'playing'", timeout=25_000)
    page.wait_for_timeout(250)


def _player_state(page: Page) -> dict[str, object]:
    return page.evaluate(
        """
        () => {
          const player = document.querySelector('#hf-player');
          const seek = document.querySelector('#scene-seek');
          return {
            paused: player.paused,
            time: player.currentTime,
            ended: document.querySelector('#stage-wrap').classList.contains('is-ended'),
            seekMax: Number(seek.max),
            seekValue: Number(seek.value),
          };
        }
        """
    )


def _drag_seek(page: Page, fraction: float) -> None:
    box = page.locator("#scene-seek").bounding_box()
    assert box, "scene seek must be visible while playing"
    x = box["x"] + box["width"] * fraction
    y = box["y"] + box["height"] / 2
    page.mouse.move(box["x"] + 2, y)
    page.mouse.down()
    page.mouse.move(x, y, steps=12)
    page.wait_for_timeout(150)
    page.mouse.up()


def test_scene_scrubber_can_be_dragged_while_paused(page: Page) -> None:
    _start_playing(page)
    # Pause first: dragging while paused must paint a frame and stay paused.
    page.click("#btn-play")
    page.wait_for_function("() => document.querySelector('#hf-player').paused === true", timeout=10_000)

    _drag_seek(page, 0.6)
    page.wait_for_timeout(500)
    state = _player_state(page)
    assert state["seekMax"] == pytest.approx(2.0, abs=0.1)
    assert 0.9 <= float(state["time"]) <= 1.6, state
    assert state["paused"] is True
    assert state["ended"] is False

    # The same control is keyboard operable: focus it and extend the range.
    page.focus("#scene-seek")
    before = _player_state(page)["seekValue"]
    page.keyboard.press("ArrowRight")
    page.wait_for_timeout(300)
    after = _player_state(page)
    assert after["seekValue"] > before
    assert after["paused"] is True


def test_scene_scrubber_resumes_playback_after_drag(page: Page) -> None:
    _start_playing(page)
    _drag_seek(page, 0.5)
    page.wait_for_timeout(600)
    state = _player_state(page)
    # Playback was running before the drag, so releasing the thumb resumes it.
    assert state["paused"] is False
    assert float(state["time"]) >= 0.6, state


def test_jump_to_end_shows_the_final_frame(page: Page) -> None:
    _start_playing(page)
    page.click("#btn-skip-end")
    page.wait_for_function(
        "() => document.querySelector('#stage-wrap').classList.contains('is-ended')",
        timeout=15_000,
    )
    page.wait_for_timeout(300)
    state = _player_state(page)
    assert state["paused"] is True
    assert float(state["time"]) >= 1.7, state
    assert state["seekValue"] == pytest.approx(float(state["seekMax"]), abs=0.1)

    # "Next" still works and the new screen clears the ended state.
    page.click("#btn-next")
    page.wait_for_function(
        "() => document.querySelector('#chapter-title').textContent === '第二屏'", timeout=15_000
    )
    page.wait_for_timeout(250)
    assert _player_state(page)["ended"] is False


def test_end_key_jumps_to_the_end_of_the_screen(page: Page) -> None:
    _start_playing(page)
    page.keyboard.press("End")
    page.wait_for_function(
        "() => document.querySelector('#stage-wrap').classList.contains('is-ended')",
        timeout=15_000,
    )
    state = _player_state(page)
    assert state["paused"] is True
    assert float(state["time"]) >= 1.7, state


def test_playing_page_fills_the_viewport_without_scrolling(page: Page) -> None:
    _start_playing(page)
    layout = page.evaluate(
        """
        () => {
          const rect = (selector) => {
            const box = document.querySelector(selector).getBoundingClientRect();
            return { x: box.x, y: box.y, width: box.width, height: box.height, bottom: box.bottom };
          };
          return {
            viewport: { width: innerWidth, height: innerHeight },
            scrollHeight: document.documentElement.scrollHeight,
            shell: rect('.deck-shell'),
            canvas: rect('.stage__canvas'),
            bar: rect('.deck-bar'),
            hint: rect('.deck-hint'),
            seek: rect('#scene-seek'),
            skip: rect('#btn-skip-end'),
          };
        }
        """
    )
    viewport = layout["viewport"]
    assert layout["scrollHeight"] <= viewport["height"] + 2
    assert layout["shell"]["width"] == pytest.approx(viewport["width"], abs=1)
    assert layout["shell"]["height"] == pytest.approx(viewport["height"], abs=1)
    assert layout["bar"]["width"] == pytest.approx(viewport["width"], abs=1)
    # The deck bar and the keyboard hint together end at the viewport bottom.
    assert max(layout["bar"]["bottom"], layout["hint"]["bottom"]) == pytest.approx(
        viewport["height"], abs=2
    )
    assert layout["bar"]["y"] > layout["canvas"]["bottom"]
    assert layout["canvas"]["width"] <= viewport["width"]
    assert layout["canvas"]["height"] <= viewport["height"]
    assert layout["canvas"]["height"] > viewport["height"] * 0.5
    assert layout["seek"]["width"] > 200
    assert layout["skip"]["width"] > 0

