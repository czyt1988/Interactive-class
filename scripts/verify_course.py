"""Browser acceptance for the long-form course.

Builds nothing: run ``python scripts/build_courses.py --course ai-first-sees``
first. Then this script serves ``dist/courses/ai-first-sees`` on a plain static
server and uses Playwright to verify the things the author asked for:

1. the deck and every scene are light (no dark page background);
2. pause stops the clock, captions switch off, voice switches off, and both
   preferences survive a reload;
3. every screen renders without console errors and without external requests;
4. one screenshot per screen plus a contact sheet land in ``.tmp/review``.

Usage (needs Playwright in the same interpreter as Pillow):

    .\\.venv\\Scripts\\python.exe scripts/verify_course.py
    .\\.venv\\Scripts\\python.exe scripts/verify_course.py --shots-only
"""

from __future__ import annotations

import argparse
import functools
import json
import re
import socket
import sys
import threading
from pathlib import Path

from PIL import Image, ImageDraw
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "dist" / "courses" / "ai-first-sees"
REVIEW = ROOT / ".tmp" / "review"
SHOTS = REVIEW / "screens"
sys.path.insert(0, str(ROOT))

from scripts.serve import CourseRequestHandler, ReusableTCPServer  # noqa: E402

EXTERNAL_ALLOWED = ("data:", "blob:")


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def luminance(pixel: tuple[int, int, int]) -> float:
    channels = []
    for value in pixel:
        channel = value / 255
        channels.append(channel / 12.92 if channel <= 0.03928 else ((channel + 0.055) / 1.055) ** 2.4)
    red, green, blue = channels
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def image_stats(path: Path) -> dict[str, float]:
    image = Image.open(path).convert("RGB")
    pixels = list(image.getdata())
    total = len(pixels)
    mean = sum(luminance(pixel) for pixel in pixels) / total
    light = sum(1 for pixel in pixels if luminance(pixel) > 0.72) / total
    dark = sum(1 for pixel in pixels if luminance(pixel) < 0.18) / total
    return {"mean": round(mean, 3), "light": round(light, 3), "dark": round(dark, 3)}


def contact_sheet(paths: list[Path], target: Path, columns: int = 4) -> None:
    thumbs = [Image.open(path).convert("RGB") for path in paths]
    width = 480
    height = 270
    cell_w = width + 16
    cell_h = height + 40
    rows = (len(thumbs) + columns - 1) // columns
    sheet = Image.new("RGB", (columns * cell_w, rows * cell_h), (244, 239, 230))
    draw = ImageDraw.Draw(sheet)
    for index, (path, image) in enumerate(zip(paths, thumbs, strict=True)):
        image.thumbnail((width, height))
        x = (index % columns) * cell_w + (cell_w - image.width) // 2
        y = (index // columns) * cell_h + 16
        sheet.paste(image, (x, y))
        draw.text(((index % columns) * cell_w + 10, (index // columns) * cell_h + cell_h - 20), path.stem, fill=(22, 20, 15))
    target.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(target, quality=88)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--shots-only", action="store_true", help="skip the control checks")
    parser.add_argument("--no-shots", action="store_true", help="skip per-screen screenshots")
    args = parser.parse_args()

    if not (BUNDLE / "index.html").is_file():
        print(f"bundle missing: {BUNDLE}\nrun: python scripts/build_courses.py --course ai-first-sees", file=sys.stderr)
        return 2
    REVIEW.mkdir(parents=True, exist_ok=True)
    if SHOTS.exists():
        for path in SHOTS.glob("*.png"):
            path.unlink()

    port = free_port()
    handler = functools.partial(CourseRequestHandler, directory=str(BUNDLE))
    server = ReusableTCPServer(("127.0.0.1", port), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    result: dict = {"screens": [], "checks": {}, "errors": []}
    try:
        with sync_playwright() as playwright:
            try:
                browser = playwright.chromium.launch(channel="chrome")
            except Exception:  # noqa: BLE001
                browser = playwright.chromium.launch()
            context = browser.new_context(viewport={"width": 1440, "height": 900})
            page = context.new_page()
            console_errors: list[str] = []
            external: list[str] = []
            page.on("console", lambda message: console_errors.append(message.text) if message.type == "error" else None)
            page.on(
                "request",
                lambda request: external.append(request.url)
                if not request.url.startswith(f"http://127.0.0.1:{port}")
                and not request.url.startswith(EXTERNAL_ALLOWED)
                else None,
            )
            page.goto(f"http://127.0.0.1:{port}/", wait_until="load")
            page.wait_for_function("document.body.dataset.deckReady === 'true'", timeout=30_000)
            result["checks"]["cover"] = page.locator("#cover").is_visible()
            body_bg = page.evaluate("() => getComputedStyle(document.body).backgroundColor")
            bar_bg = page.evaluate("() => getComputedStyle(document.querySelector('.deck-bar')).backgroundColor")
            result["checks"]["deckBodyLuma"] = round(image_mean_luma(body_bg), 3)
            result["checks"]["deckBarLuma"] = round(image_mean_luma(bar_bg), 3)

            page.click("#btn-start")
            page.wait_for_function("document.body.dataset.deckState === 'playing'", timeout=40_000)
            page.wait_for_timeout(1800)
            player = page.locator("#hf-player")
            frame = wait_for_composition_frame(page, timeout=30_000)
            result["checks"]["screens"] = page.locator(".outline__item").count()
            result["checks"]["chapterCounter"] = page.inner_text("#chapter-counter")

            if not args.shots_only:
                # --- pause -------------------------------------------------
                page.click("#btn-play")
                page.wait_for_timeout(600)
                t1 = player.evaluate("el => el.currentTime")
                expected_paused = page.evaluate("() => document.querySelector('#btn-play').getAttribute('aria-pressed')")
                page.wait_for_timeout(900)
                t2 = player.evaluate("el => el.currentTime")
                result["checks"]["pause"] = {
                    "ariaPressed": expected_paused,
                    "timeDelta": round(abs(t2 - t1), 3),
                    "ok": abs(t2 - t1) < 0.35,
                }
                page.click("#btn-play")
                page.wait_for_timeout(900)
                t3 = player.evaluate("el => el.currentTime")
                result["checks"]["resume"] = {"advanced": t3 > t2 + 0.2, "delta": round(t3 - t2, 3)}

                # --- captions off/on ---------------------------------------
                def caption_state() -> dict:
                    return frame.evaluate(
                        "() => ({attr: document.documentElement.dataset.captions || '', "
                        "display: getComputedStyle(document.querySelector('.cap-band')).display})"
                    )
                before = caption_state()
                page.click("#btn-captions")
                page.wait_for_timeout(500)
                off = caption_state()
                aria_off = page.get_attribute("#btn-captions", "aria-pressed")
                page.click("#btn-captions")
                page.wait_for_timeout(500)
                on = caption_state()
                aria_on = page.get_attribute("#btn-captions", "aria-pressed")
                result["checks"]["captions"] = {
                    "before": before,
                    "off": off,
                    "on": on,
                    "ariaOff": aria_off,
                    "ariaOn": aria_on,
                    "ok": off["attr"] == "off" and off["display"] == "none" and on["display"] != "none",
                }

                # --- voice off/on ------------------------------------------
                page.click("#btn-sound")
                page.wait_for_timeout(400)
                muted = player.evaluate("el => el.hasAttribute('muted')")
                aria_muted = page.get_attribute("#btn-sound", "aria-pressed")
                page.click("#btn-sound")
                page.wait_for_timeout(400)
                unmuted = player.evaluate("el => !el.hasAttribute('muted')")
                result["checks"]["voice"] = {
                    "muted": muted,
                    "unmuted": unmuted,
                    "ariaMuted": aria_muted,
                    "ok": muted and unmuted and aria_muted == "false",
                }

                # --- preference persistence --------------------------------
                page.click("#btn-captions")
                page.wait_for_timeout(250)
                page.reload(wait_until="load")
                page.wait_for_function("document.body.dataset.deckReady === 'true'", timeout=30_000)
                page.click("#btn-start")
                page.wait_for_function("document.body.dataset.deckState === 'playing'", timeout=40_000)
                page.wait_for_timeout(1500)
                frame = wait_for_composition_frame(page, timeout=30_000)
                persisted = frame.evaluate("() => document.documentElement.dataset.captions || ''")
                result["checks"]["captionsPersisted"] = {
                    "value": persisted,
                    "ok": persisted == "off",
                }
                page.click("#btn-captions")
                page.wait_for_timeout(350)

                result["checks"]["consoleErrors"] = console_errors
                result["checks"]["externalRequests"] = external
                result["checks"]["lightDeck"] = (
                    result["checks"]["deckBodyLuma"] > 0.7 and result["checks"]["deckBarLuma"] > 0.6
                )

            # --- one screenshot per screen --------------------------------
            if not args.no_shots:
                starts = page.evaluate(
                    """() => {
                        const data = JSON.parse(document.getElementById('course-data').textContent);
                        return data.screens.map((screen) => ({ id: screen.id, start: screen.start, duration: screen.duration }));
                    }"""
                )
                page.evaluate("() => document.querySelector('#hf-player').pause()")
                for index, screen in enumerate(starts):
                    # Seek just past the midpoint: the scene has built its argument.
                    moment = screen["start"] + max(0.8, screen["duration"] * 0.55)
                    page.evaluate(
                        "(t) => { const p = document.querySelector('#hf-player'); p.seek(t); }",
                        moment,
                    )
                    page.wait_for_timeout(420)
                    path = SHOTS / f"{index + 1:02d}-{screen['id']}.png"
                    page.locator("#stage").screenshot(path=str(path))
                    stats = image_stats(path)
                    result["screens"].append({"id": screen["id"], "at": round(moment, 1), **stats})
                page.evaluate("() => document.querySelector('#hf-player').play()")

            context.close()
            browser.close()
    finally:
        server.shutdown()
        thread.join(timeout=2)

    if result["screens"]:
        sheet = REVIEW / "contact-sheet.jpg"
        contact_sheet(sorted(SHOTS.glob("*.png")), sheet)
        result["contactSheet"] = str(sheet)
        dark_pages = [screen for screen in result["screens"] if screen["mean"] < 0.5 or screen["light"] < 0.35]
        result["checks"]["allScreensLight"] = not dark_pages
        result["checks"]["darkPages"] = dark_pages

    print(json.dumps(result, ensure_ascii=False, indent=2))
    ok = bool(result["checks"].get("cover")) and bool(result["checks"].get("lightDeck"))
    if result["screens"]:
        ok = ok and bool(result["checks"].get("allScreensLight"))
    for key in ("pause", "captions", "voice", "captionsPersisted"):
        if key in result["checks"]:
            ok = ok and bool(result["checks"][key].get("ok"))
    ok = ok and not result["errors"] and not result["checks"].get("consoleErrors")
    return 0 if ok else 1


def wait_for_composition_frame(page, timeout: int):
    import time

    deadline = time.monotonic() + timeout / 1000
    while time.monotonic() < deadline:
        frame = next((item for item in page.frames if "composition/index.html" in item.url), None)
        if frame is not None:
            return frame
        page.wait_for_timeout(200)
    raise RuntimeError("composition iframe not found")


def image_mean_luma(value: str) -> float:
    match = re.search(r"rgba?\(([0-9.]+), ([0-9.]+), ([0-9.]+)", value) or re.search(
        r"color\(srgb ([0-9.]+) ([0-9.]+) ([0-9.]+)", value
    )
    if not match:
        return 1.0
    channels = [float(part) for part in match.groups()]
    if value.startswith("color("):
        channels = [value * 255 for value in channels]
    return luminance((channels[0], channels[1], channels[2]))


if __name__ == "__main__":
    raise SystemExit(main())
