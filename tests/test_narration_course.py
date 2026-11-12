"""Contract tests for the long-form narrated course `courses/ai-first-sees`.

These tests do not regenerate narration (no network). They pin the shape the
generator must keep producing: 22 narration-driven scenes, continuous playback,
one voice track per scene in the root composition, captions inside the
1920x1080 canvas, and the light-only visual rule the author asked for.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from app.catalog.resolver import resolve_course

ROOT = Path(__file__).resolve().parent.parent
COURSE = ROOT / "courses" / "ai-first-sees"
COMPOSITION = COURSE / "composition"

SCENE_COUNT = 22


@pytest.fixture(scope="module")
def resolved():
    return resolve_course(COURSE)


def test_long_form_contract(resolved) -> None:
    assert resolved.slug == "ai-first-sees"
    assert resolved.audio is True
    assert resolved.playback == "continuous"
    assert len(resolved.screens) == SCENE_COUNT
    # 旁白语速从 -15% 调到 +0% 后全片约 18:38；这里只确认它仍是长课，不是短课。
    assert resolved.composition.duration > 15 * 60
    assert resolved.stats.estimatedMinutes >= 16
    for screen in resolved.screens:
        assert screen.transcript, f"{screen.id} 缺少旁白文本"
        assert screen.autoAdvance is True, f"{screen.id} 必须自动接续"
        assert screen.duration > 5
        # S06 is the long "scaling + emergence" scene; one page can be > 90 s.
        assert screen.duration < 180, f"{screen.id} 时长 {screen.duration} 异常"


def test_scene_hosts_are_contiguous(resolved) -> None:
    previous_end = 0.0
    for screen in resolved.screens:
        assert abs(screen.start - previous_end) < 0.01, f"{screen.id} 与上一屏之间有空洞"
        previous_end = screen.start + screen.duration
    assert abs(previous_end - resolved.composition.duration) < 0.01


def test_one_audio_track_per_scene() -> None:
    root = (COMPOSITION / "index.html").read_text(encoding="utf-8")
    audio_tags = re.findall(r"<audio\b[\s\S]*?</audio>", root)
    assert len(audio_tags) == SCENE_COUNT
    ids = re.findall(r'<audio\s+id="nar-([a-z0-9-]+)"', root)
    assert len(ids) == SCENE_COUNT
    manifest = json.loads((COURSE / "course.json").read_text(encoding="utf-8"))
    assert set(ids) == {screen["id"] for screen in manifest["screens"]}
    for tag in audio_tags:
        assert 'class="clip"' in tag
        assert "data-start=" in tag
        assert "data-duration=" in tag
        src = re.search(r'src="([^"]+)"', tag)
        assert src, "audio 缺少 src"
        path = COMPOSITION / src.group(1)
        assert path.is_file(), f"音频不存在：{path}"
        assert path.suffix in {".ogg", ".opus", ".mp3", ".m4a", ".aac"}


def test_captions_are_inside_the_canvas() -> None:
    scenes = sorted((COMPOSITION / "compositions").glob("*.html"))
    assert len(scenes) == SCENE_COUNT
    for scene in scenes:
        source = scene.read_text(encoding="utf-8")
        assert "<!-- CAPTIONS:BEGIN -->" in source, f"{scene.name} 缺少字幕块"
        assert 'class="cap-band"' in source, f"{scene.name} 缺少旁白条"
        starts = [
            float(value)
            for value in re.findall(r'class="cap-line clip" data-start="([0-9.]+)"', source)
        ]
        assert starts, f"{scene.name} 没有可计时的字幕"
        assert starts == sorted(starts), f"{scene.name} 的字幕时间没有递增"
        # Timing data is generated, never hand-written.
        assert "// TIMING:BEGIN" in source
        assert "const N = {" in source
        assert 'window.__timelines["s-' in source


def test_audio_budget() -> None:
    audio_dir = COMPOSITION / "assets" / "audio"
    total = sum(path.stat().st_size for path in audio_dir.glob("*.ogg"))
    assert total > 3_000_000, f"旁白音频合计 {total} 字节，疑似缺文件"
    # The bundle budget is 15 MB; narration is the largest single item.
    assert total < 8_000_000, f"旁白音频合计 {total} 字节，超出预算"


def test_media_is_local_and_small() -> None:
    """Real logos / screenshots are allowed, but only local files and small cards."""

    media = COMPOSITION / "assets" / "media"
    files = [path for path in media.rglob("*") if path.is_file()]
    assert files, "assets/media 为空：先跑 scripts/prepare_course_media.py"
    for path in files:
        assert path.stat().st_size <= 500 * 1024, f"{path} 超过单图 500 KB 预算"
    assert (media / "logo" / "deepmind.png").is_file()
    assert (media / "shot" / "dsh-desktop.webp").is_file()


def test_whole_course_is_light() -> None:
    """The author explicitly ruled out dark page backgrounds after the first cut."""

    css = (COMPOSITION / "assets" / "course.css").read_text(encoding="utf-8")
    assert '[data-theme="dark"]' not in css
    assert '[data-theme="night"]' not in css
    assert "#0b0b0c" not in css
    assert "#121417" not in css

    manifest = json.loads((COURSE / "course.json").read_text(encoding="utf-8"))
    assert len(manifest["screens"]) == SCENE_COUNT

    theme_re = re.compile(r'data-theme="([a-z-]+)"')
    for scene in sorted((COMPOSITION / "compositions").glob("*.html")):
        themes = theme_re.findall(scene.read_text(encoding="utf-8"))
        assert themes == ["paper"], f"{scene.name} 使用了非浅色主题：{themes}"


def test_player_has_pause_subtitle_and_voice_controls() -> None:
    shell = (ROOT / "runtime" / "shell.html.j2").read_text(encoding="utf-8")
    assert 'id="btn-play"' in shell
    assert 'id="btn-captions"' in shell
    assert 'id="btn-sound"' in shell
    assert "C 字幕" in shell
    assert "M 配音" in shell

    deck_js = (ROOT / "runtime" / "course-deck.js").read_text(encoding="utf-8")
    assert "course-captions" in deck_js
    assert "toggleCaptions" in deck_js
    assert "PREF_CAPTIONS" in deck_js
    assert "PREF_SOUND" in deck_js
    assert "togglePlay" in deck_js

    deck_css = (ROOT / "runtime" / "course-deck.css").read_text(encoding="utf-8")
    assert "control--cc" in deck_css

    # The root composition hides the burned-in caption band on request.
    root = (COMPOSITION / "index.html").read_text(encoding="utf-8")
    assert 'action === "course-captions"' in root
    assert 'html[data-captions="off"] .cap-band' in (COMPOSITION / "assets" / "course.css").read_text(
        encoding="utf-8"
    )
