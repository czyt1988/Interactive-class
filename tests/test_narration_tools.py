"""Unit tests for the narration authoring tool's cache and rate handling.

The pipeline reuses ``narration/cache`` so reruns do not need the network. These
tests pin the invalidation rule: a cached track is only reusable when the voice,
the rate and the narration text all match. Otherwise tuning the speed would
silently keep the old, slower audio.
"""

from __future__ import annotations

import argparse

import pytest

from scripts import build_narration as narration

VOICE = "zh-CN-YunxiNeural"


def make_scene(narration_text: str = "你好，这是一段旁白。") -> narration.Scene:
    return narration.Scene(
        code="S01",
        id="hook",
        act="act-1",
        actLabel="第一幕 · 看",
        theme="paper",
        accent="#2FB68A",
        title="标题",
        thesis="论题",
        screenText="屏幕文字",
        visual="画面",
        animation="动画",
        facts="事实",
        materials="素材",
        keywords=["关键词"],
        narration=narration_text,
    )


@pytest.mark.parametrize("value", ["-15%", "-5%", "0%", "+0%", "5%", "15%"])
def test_normalize_rate_always_emits_a_signed_percentage(value: str) -> None:
    normalized = narration.normalize_rate(value)
    assert normalized.startswith(("+", "-"))
    assert normalized.endswith("%")
    # The normalized form is what edge-tts accepts: an int plus percent sign.
    int(normalized[:-1])


def test_normalize_rate_keeps_the_sign() -> None:
    assert narration.normalize_rate("-15%") == "-15%"
    assert narration.normalize_rate("0%") == "+0%"
    assert narration.normalize_rate(" 15% ") == "+15%"


@pytest.mark.parametrize("value", ["fast", "", "15", "+15", "abc%"])
def test_normalize_rate_rejects_invalid_values(value: str) -> None:
    with pytest.raises(argparse.ArgumentTypeError):
        narration.normalize_rate(value)


def test_cache_entry_depends_on_voice_rate_and_text() -> None:
    scene = make_scene()
    base = narration.cache_entry(scene, VOICE, "+0%")
    assert base == narration.cache_entry(scene, VOICE, "+0%")
    assert base != narration.cache_entry(scene, "zh-CN-YunyangNeural", "+0%")
    assert base != narration.cache_entry(scene, VOICE, "-15%")
    assert base != narration.cache_entry(make_scene("换了一句旁白。"), VOICE, "+0%")


def test_cache_is_fresh_only_for_matching_config(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(narration, "CACHE", tmp_path)
    monkeypatch.setattr(narration, "CACHE_MANIFEST", tmp_path / "manifest.json")
    scene = make_scene()
    (tmp_path / "s01-hook.mp3").write_bytes(b"\x00" * 4096)
    (tmp_path / "s01-hook.srt").write_text("1\n00:00:00,000 --> 00:00:02,000\n你好\n", encoding="utf-8")
    narration.write_cache_manifest([scene], VOICE, "+0%")

    assert narration.cache_is_fresh(scene, VOICE, "+0%")
    assert not narration.cache_is_fresh(scene, VOICE, "-15%")
    assert not narration.cache_is_fresh(scene, "zh-CN-YunyangNeural", "+0%")
    assert not narration.cache_is_fresh(make_scene("文本改了。"), VOICE, "+0%")
