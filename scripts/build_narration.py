"""Narration pipeline for the long-form course `courses/ai-first-sees`.

One scene = one page = one narration clip. The voice is the clock:

1. Read ``narration/scenes.json`` (authored from the course outline + fact check).
2. Generate one voice track per scene with edge-tts, plus its sentence timings.
3. Transcode to OGG/Opus (small enough for the 15 MB course budget).
4. Derive caption lines from the sentence timings, split to <= 30 chars.
5. Write ``composition/assets/narration-data.js``, the root composition with
   every scene host + one <audio> per scene, ``course.json``, scene skeletons and
   ``STORYBOARD.md``.

Re-running is safe: TTS results are cached, scene files only get created when
missing (``--force-scaffold`` to reset), and captions are patched between the
``CAPTIONS:BEGIN`` / ``CAPTIONS:END`` markers so authored animation is kept.

This script is course tooling, not part of the runtime. It needs the optional
authoring packages: ``pip install edge-tts mutagen soundfile`` (the audio is
committed, so playback never needs them).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import subprocess
import sys
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

CJK = r"\u3400-\u9fff"

ROOT = Path(__file__).resolve().parents[1]
COURSE = ROOT / "courses" / "ai-first-sees"
NARRATION_DIR = COURSE / "narration"
COMPOSITION = COURSE / "composition"
SCENES_SRC = NARRATION_DIR / "scenes.json"
CACHE = NARRATION_DIR / "cache"
CACHE_MANIFEST = CACHE / "manifest.json"
AUDIO_DIR = COMPOSITION / "assets" / "audio"
SCENE_DIR = COMPOSITION / "compositions"

SCENE_TEMPLATE = """<template>
  <style>
    /* Scene-specific styles for {code} {id}. Shared primitives live in assets/course.css. */
  </style>

  <div
    id="root"
    class="scene-root"
    data-composition-id="s-{id}"
    data-width="1920"
    data-height="1080"
    data-theme="{theme}"
    data-act="{act}"
  >
    <div class="scene-in">
      <header class="scene-head">
        <p class="scene-kicker">
          <span class="scene-code">{code}</span>
          <span class="scene-act">{act_label}</span>
        </p>
        <h1 id="s-{id}-title" class="scene-title">{title}</h1>
        <p class="scene-no">{index:02d} / {total:02d}</p>
      </header>

      <section id="s-{id}-stage" class="stage">
        <!-- VISUAL: {visual} -->
      </section>
    </div>

    <!-- CAPTIONS:BEGIN -->
    <footer class="cap-band">
      <div class="cap-lines">
        {caption_lines}
      </div>
      <div class="cap-foot">
        <span class="cap-code">{code}</span>
        <span class="cap-clock">{duration_clock}</span>
      </div>
    </footer>
    <!-- CAPTIONS:END -->
  </div>

  <script>
    // TIMING:BEGIN -- generated from the narration track by scripts/build_narration.py
    const N = {timing_json};
    // TIMING:END
    const tl = gsap.timeline({{ paused: true }});

    // 入场：从场景底色淡入，切到下一页时像视频一样接上。
    tl.fromTo(".scene-in", {{ opacity: 0 }}, {{ opacity: 1, duration: 0.35, ease: "power2.out" }}, 0);

    // MOTION:BEGIN
    // 用 N.cues[i].t 把每一个动效钉在旁白的句子上：
    // tl.fromTo("#s-{id}-x", {{ opacity: 0, y: 20 }}, {{ opacity: 1, y: 0, duration: 0.5, ease: "power3.out" }}, N.cues[0].t);
    // MOTION:END

    window.__timelines["s-{id}"] = tl;
  </script>
</template>
"""

TIMING_BEGIN = '// TIMING:BEGIN'
TIMING_END = '// TIMING:END'

CAPTION_BEGIN = "<!-- CAPTIONS:BEGIN -->"
CAPTION_END = "<!-- CAPTIONS:END -->"

CAPTION_BAND = """<footer class="cap-band">
      <div class="cap-lines">
        {caption_lines}
      </div>
      <div class="cap-foot">
        <span class="cap-code">{code}</span>
        <span class="cap-clock">{duration_clock}</span>
      </div>
    </footer>"""


@dataclass
class Scene:
    code: str
    id: str
    act: str
    actLabel: str
    theme: str
    accent: str
    title: str
    thesis: str
    screenText: str
    visual: str
    animation: str
    facts: str
    materials: str
    keywords: list[str]
    narration: str
    # timing, filled by the pipeline
    audio_start: float = 0.0
    audio_duration: float = 0.0
    duration: float = 0.0
    start: float = 0.0
    cues: list[dict] | None = None
    audio_file: str = ""


# --------------------------------------------------------------------- helpers


def clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def text_len(text: str) -> int:
    """Rough caption width: CJK/fullwidth count 2, ASCII counts 1."""
    total = 0
    for char in text:
        total += 2 if unicodedata.east_asian_width(char) in ("W", "F") else 1
    return total


def split_caption_lines(text: str, max_width: int = 56) -> list[str]:
    """Split one narration sentence into caption lines of <= max_width.

    Breaks at sentence and comma/colon boundaries; enumeration commas (、)
    stay with their item so a line never dangles on a 、.
    """
    text = clean_text(text)
    if not text:
        return []

    def pack(parts: list[str]) -> list[str]:
        lines: list[str] = []
        buffer = ""
        for part in parts:
            if not part:
                continue
            if text_len(buffer + part) <= max_width:
                buffer += part
                continue
            if buffer:
                lines.append(buffer)
                buffer = ""
            if text_len(part) <= max_width:
                buffer = part
                continue
            current = ""
            for char in part:
                if text_len(current + char) > max_width and current:
                    lines.append(current)
                    current = ""
                current += char
            buffer = current
        if buffer:
            lines.append(buffer)
        return lines

    sentences = re.findall(r"[^。！？；…]+[。！？；…]?", text) or [text]
    lines: list[str] = []
    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue
        if text_len(sentence) <= max_width:
            lines.append(sentence)
            continue
        clauses = re.findall(r"[^，：；]+[，：；]?", sentence) or [sentence]
        lines.extend(pack([clause.strip() for clause in clauses if clause.strip()]))

    merged: list[str] = []
    for line in lines:
        if merged and text_len(merged[-1]) + text_len(line) <= max_width + 10:
            merged[-1] += line
        else:
            merged.append(line)
    return merged


def parse_srt(path: Path) -> list[dict]:
    raw = path.read_text(encoding="utf-8").strip()
    if not raw:
        return []
    cues: list[dict] = []
    blocks = re.split(r"\r?\n\r?\n", raw)
    for block in blocks:
        lines = [line for line in block.splitlines() if line.strip()]
        if len(lines) < 3:
            continue
        time_line = lines[1]
        match = re.match(
            r"(\d{2}):(\d{2}):(\d{2}),(\d{3})\s*-->\s*(\d{2}):(\d{2}):(\d{2}),(\d{3})",
            time_line,
        )
        if not match:
            continue
        h1, m1, s1, ms1, h2, m2, s2, ms2 = (int(value) for value in match.groups())
        start = h1 * 3600 + m1 * 60 + s1 + ms1 / 1000
        end = h2 * 3600 + m2 * 60 + s2 + ms2 / 1000
        text = clean_text("".join(lines[2:]))
        if text:
            cues.append({"start": start, "end": end, "text": text})
    return cues


def clock(seconds: float) -> str:
    total = max(0, round(seconds))
    return f"{total // 60:02d}:{total % 60:02d}"


def normalize_rate(value: str) -> str:
    """edge-tts wants a signed prosody rate: "-15%" works, bare "0%" is invalid."""
    text = value.strip()
    if text.endswith("%"):
        number = text[:-1].strip()
        try:
            int(number)
        except ValueError:
            number = ""
        if number:
            if number[0] not in "+-":
                number = "+" + number
            return f"{number}%"
    raise argparse.ArgumentTypeError(
        f'语速要写成带符号的百分比，例如 "-15%" 或 "+0%"，收到 {value!r}'
    )


def cache_paths(scene: Scene) -> tuple[Path, Path]:
    return (
        CACHE / f"{scene.code.lower()}-{scene.id}.mp3",
        CACHE / f"{scene.code.lower()}-{scene.id}.srt",
    )


def text_fingerprint(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]


def cache_entry(scene: Scene, voice: str, rate: str) -> dict:
    """What a cached TTS pair depends on: the voice, the rate and the text itself."""
    return {"voice": voice, "rate": rate, "text": text_fingerprint(scene.narration)}


def load_cache_manifest() -> dict[str, dict]:
    try:
        payload = json.loads(CACHE_MANIFEST.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    items = payload.get("items")
    return items if isinstance(items, dict) else {}


def cache_is_fresh(scene: Scene, voice: str, rate: str) -> bool:
    mp3, srt = cache_paths(scene)
    if not (mp3.is_file() and srt.is_file() and mp3.stat().st_size > 1000):
        return False
    key = f"{scene.code.lower()}-{scene.id}"
    return load_cache_manifest().get(key) == cache_entry(scene, voice, rate)


def write_cache_manifest(scenes: list[Scene], voice: str, rate: str) -> None:
    CACHE.mkdir(parents=True, exist_ok=True)
    payload = {
        "voice": voice,
        "rate": rate,
        "items": {
            f"{scene.code.lower()}-{scene.id}": cache_entry(scene, voice, rate)
            for scene in scenes
        },
    }
    CACHE_MANIFEST.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n"
    )


def run_tts(scene: Scene, voice: str, rate: str) -> tuple[Path, Path]:
    mp3, srt = cache_paths(scene)
    CACHE.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable,
        "-m",
        "edge_tts",
        "--voice",
        voice,
        f"--rate={rate}",
        "--text",
        scene.narration,
        "--write-media",
        str(mp3),
        "--write-subtitles",
        str(srt),
    ]
    subprocess.run(command, check=True, capture_output=True, text=True, encoding="utf-8")
    return mp3, srt


def transcode_to_opus(mp3: Path, target: Path) -> float:
    """Decode the TTS mp3 and write a compact OGG/Opus file. Returns duration."""
    import soundfile as sf

    data, sample_rate = sf.read(str(mp3), dtype="int16")
    target.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(target), data, sample_rate, format="OGG", subtype="OPUS")
    info = sf.info(str(target))
    return info.frames / info.samplerate


def build_cues(scene: Scene, srt_cues: list[dict], lead: float) -> list[dict]:
    cues: list[dict] = []
    index = 0
    previous_end = 0.0
    for srt_cue in srt_cues:
        start = srt_cue["start"]
        end = max(srt_cue["end"], start + 0.2)
        text = srt_cue["text"]
        lines = split_caption_lines(text)
        if not lines:
            continue
        total_width = sum(text_len(line) for line in lines) or 1
        cursor = start
        for line in lines:
            share = text_len(line) / total_width
            cue_start = max(cursor, previous_end)
            cue_end = max(cue_start + 0.35, cursor + (end - start) * share - 0.04)
            cues.append(
                {
                    "i": index,
                    "t": round(lead + cue_start, 3),
                    "d": round(max(0.35, cue_end - cue_start), 3),
                    "text": line,
                    "sent": text,
                }
            )
            index += 1
            previous_end = cue_end
            cursor += (end - start) * share
    return cues


def scene_clock(duration: float) -> str:
    return clock(duration)


# ------------------------------------------------------------------ generators


def write_root(scenes: list[Scene], total: float) -> None:
    hosts: list[str] = []
    audios: list[str] = []
    for i, scene in enumerate(scenes):
        hosts.append(
            f"""      <div
        id="s-{scene.id}"
        data-screen-id="{scene.id}"
        data-composition-id="s-{scene.id}"
        data-composition-src="compositions/{i + 1:02d}-{scene.id}.html"
        data-start="{scene.start:g}"
        data-duration="{scene.duration:g}"
        data-track-index="{i}"
        data-track-kind="graphics"
        data-width="1920"
        data-height="1080"
      ></div>"""
        )
        audios.append(
            f"""      <audio
        id="nar-{scene.id}"
        class="clip"
        data-start="{scene.audio_start:g}"
        data-duration="{scene.audio_duration:.3f}"
        data-track-index="{100 + i}"
        data-volume="1"
        src="assets/audio/{scene.code.lower()}-{scene.id}.ogg"
      ></audio>"""
        )
    html = f"""<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=1920, height=1080" />
    <title>从会聊天到会干活：AI Agent 入门</title>
    <script src="assets/vendor/gsap.min.js"></script>
    <link rel="stylesheet" href="assets/course.css" />
  </head>
  <body>
    <div
      id="root"
      data-composition-id="main"
      data-start="0"
      data-duration="{total:g}"
      data-width="1920"
      data-height="1080"
    >
{chr(10).join(hosts)}

      <!-- One voice track per scene. The deck plays the whole root timeline
           continuously; each track starts when its scene starts. -->
{chr(10).join(audios)}
    </div>

    <script>
      window.__timelines = window.__timelines || {{}};
      window.__timelines["main"] = gsap.timeline({{ paused: true }});

      /* Caption preference. The deck posts a normal HyperFrames control
         message; unknown actions are ignored by the runtime, ours is handled
         here. Hiding the band is a viewer preference, the burned-in captions
         for MP4 export are unchanged. */
      (function () {{
        const root = document.documentElement;
        const apply = (visible) => {{
          if (visible) delete root.dataset.captions;
          else root.dataset.captions = "off";
        }};
        window.addEventListener("message", (event) => {{
          const message = event.data;
          if (!message || message.source !== "hf-parent" || message.type !== "control") return;
          if (message.action === "course-captions") apply(message.visible !== false);
        }});
        try {{
          if (localStorage.getItem("ai-learning:captions") === "off") apply(false);
        }} catch (error) {{
          /* storage can be blocked; captions stay on */
        }}
      }})();
    </script>
  </body>
</html>
"""
    (COMPOSITION / "index.html").write_text(html, encoding="utf-8", newline="\n")


def write_narration_data(scenes: list[Scene], total: float) -> None:
    payload = {
        "duration": round(total, 2),
        "scenes": {
            scene.id: {
                "code": scene.code,
                "index": index,
                "start": round(scene.start, 3),
                "duration": scene.duration,
                "audioStart": scene.audio_start,
                "audioDuration": round(scene.audio_duration, 3),
                "cues": scene.cues,
            }
            for index, scene in enumerate(scenes)
        },
    }
    js = "/* Generated by scripts/build_narration.py. Do not edit by hand. */\n"
    js += "window.__NARRATION = " + json.dumps(payload, ensure_ascii=False, indent=2) + ";\n"
    (COMPOSITION / "assets" / "narration-data.js").write_text(js, encoding="utf-8", newline="\n")


def write_composition_course(scenes: list[Scene], meta: dict) -> None:
    course = {
        "schemaVersion": 1,
        "slug": meta["slug"],
        "title": meta["title"],
        "subtitle": meta["subtitle"],
        "summary": meta["summary"],
        "description": meta["description"],
        "level": meta["level"],
        "tags": meta["tags"],
        "language": meta["language"],
        "status": meta["status"],
        "featured": meta["featured"],
        "order": meta["order"],
        "accent": meta["accent"],
        "outcomes": meta["outcomes"],
        "prerequisites": meta["prerequisites"],
        "takeaways": meta["takeaways"],
        "audio": True,
        "interactive": False,
        "playback": "continuous",
        "composition": {
            "entry": "composition/index.html",
            "width": 1920,
            "height": 1080,
            "fps": 30,
        },
        "screens": [
            {
                "id": scene.id,
                "kicker": scene.actLabel,
                "title": scene.title,
                "summary": scene.thesis,
                "transcript": scene.narration,
                "autoAdvance": True,
                "keywords": scene.keywords,
            }
            for scene in scenes
        ],
        "site": {"homeUrl": "/courses", "backLabel": "返回课程库"},
        "credits": {
            "author": "AI Learning",
            "updatedAt": meta["updatedAt"],
            "sources": meta["sources"],
        },
    }
    (COURSE / "course.json").write_text(
        json.dumps(course, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n"
    )


def timing_constant(scene: Scene) -> str:
    payload = {
        "code": scene.code,
        "id": scene.id,
        "index": 0,
        "start": 0,
        "duration": scene.duration,
        "audioStart": scene.audio_start - scene.start,
        "audioDuration": round(scene.audio_duration, 3),
        "cues": scene.cues,
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def render_caption_markup(scene: Scene) -> str:
    lines = []
    for cue in scene.cues or []:
        text = (
            cue["text"]
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )
        lines.append(
            f'        <p id="s-{scene.id}-cap-{cue["i"]}" class="cap-line clip" '
            f'data-start="{cue["t"]:g}" data-duration="{cue["d"]:g}">{text}</p>'
        )
    return "\n".join(lines)


def render_caption_band(scene: Scene) -> str:
    return CAPTION_BAND.format(
        caption_lines=render_caption_markup(scene),
        code=scene.code,
        id=scene.id,
        duration_clock=scene_clock(scene.duration),
    )


def write_scene_skeletons(scenes: list[Scene], force: bool) -> None:
    SCENE_DIR.mkdir(parents=True, exist_ok=True)
    total = len(scenes)
    for i, scene in enumerate(scenes):
        path = SCENE_DIR / f"{i + 1:02d}-{scene.id}.html"
        if path.is_file() and not force:
            continue
        text = SCENE_TEMPLATE.format(
            code=scene.code,
            id=scene.id,
            theme=scene.theme,
            act=scene.act,
            act_label=scene.actLabel,
            title=scene.title,
            index=i + 1,
            total=total,
            visual=scene.visual,
            caption_lines=render_caption_markup(scene),
            duration_clock=scene_clock(scene.duration),
            timing_json=timing_constant(scene),
        )
        path.write_text(text, encoding="utf-8", newline="\n")


def patch_scene_captions(scenes: list[Scene]) -> None:
    for i, scene in enumerate(scenes):
        path = SCENE_DIR / f"{i + 1:02d}-{scene.id}.html"
        if not path.is_file():
            continue
        source = path.read_text(encoding="utf-8")
        if TIMING_BEGIN in source and TIMING_END in source:
            head, rest = source.split(TIMING_BEGIN, 1)
            _, tail = rest.split(TIMING_END, 1)
            source = head + TIMING_BEGIN + "\n    const N = " + timing_constant(scene) + ";\n    " + TIMING_END + tail
        if CAPTION_BEGIN not in source or CAPTION_END not in source:
            path.write_text(source, encoding="utf-8", newline="\n")
            continue
        head, rest = source.split(CAPTION_BEGIN, 1)
        _, tail = rest.split(CAPTION_END, 1)
        band = "\n    " + render_caption_band(scene) + "\n    "
        path.write_text(head + CAPTION_BEGIN + band + CAPTION_END + tail, encoding="utf-8", newline="\n")


def write_storyboard(
    scenes: list[Scene], total: float, voice: str, rate: str, lead: float, tail: float
) -> None:
    rows = []
    audio_seconds = sum(scene.audio_duration for scene in scenes)
    narrated_chars = sum(len(clean_text(scene.narration)) for scene in scenes)
    chars_per_second = narrated_chars / audio_seconds if audio_seconds else 0.0
    for i, scene in enumerate(scenes):
        rows.append(
            f"| {i + 1} | {scene.code} | {scene.id} | {scene.title} | {scene.thesis} | "
            f"{scene.clock_start if hasattr(scene, 'clock_start') else scene_clock(scene.start)} | "
            f"{scene.duration:.1f}s | {len(scene.cues or [])} |"
        )
    table = "\n".join(rows)
    text = f"""# {scenes[0].code} → {scenes[-1].code}：从会聊天到会干活

## 学习者

用过 ChatGPT 的普通职场人；听说过 Agent、Harness、MCP，但分不清的人；不需要编程和数学基础。

## 学完能

1. 分清 CNN / AlphaGo 与 LLM / ChatGPT 是两条不同的技术路线。
2. 说出 Agent 的三级跳，以及提示词型与 Harness 型的区别。
3. 解释「大模型 API 默认无状态」，并知道什么时候该新开会话。
4. 说出 Harness 的四大件：工具、Skill、MCP、行动循环。
5. 写出一份目录级的 AGENTS.md，并知道怎么选模型、用斜杠命令控制任务范围。
6. 判断哪些信息不能交给 Agent，以及怎么给权限。

## 屏幕

一个 S 编号 = 一个场景 = 一页动态 PPT。每页时长由旁白长度决定（旁白念完 + 1.6 秒收尾）。
根 composition 的 `data-start` / `data-duration` 由 `scripts/build_narration.py` 从旁白音频计算，不要手改。

总时长：{clock(total)}（{total:.1f} 秒），{len(scenes)} 个场景。

| # | S | id | 标题 | 一句话论题 | 起点 | 时长 | 字幕行 |
| --- | --- | --- | --- | --- | --- | --- | --- |
{table}

## 进度节奏

- 旁白语速：edge-tts `{voice}`，rate {rate}，约 {chars_per_second:.1f} 字/秒。
- 每页：{lead:g} 秒入场，旁白，结束留 {tail:g} 秒收尾；下一页从上一页结束处无缝接上。
- 所有动效由 `N.cues[i].t`（旁白句子时间）驱动，不按固定间隔自行播放。

## 参考

见 `courses-outline/ai-first-sees/outline.md`；产品数据口径统一为「截至 2026-11-12」。
"""
    (COURSE / "STORYBOARD.md").write_text(text, encoding="utf-8", newline="\n")


# ----------------------------------------------------------------------- main


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build narration audio, timings and course scaffolding")
    parser.add_argument("--voice", default="zh-CN-YunxiNeural")
    parser.add_argument("--rate", type=normalize_rate, default="+0%", help='语速，如 "-15%"、"+0%"')
    parser.add_argument("--lead", type=float, default=0.6, help="seconds before narration starts")
    parser.add_argument("--tail", type=float, default=1.6, help="seconds held after narration")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument(
        "--no-tts",
        action="store_true",
        help="reuse narration/cache only when it matches the current voice, rate and text",
    )
    parser.add_argument("--force-scaffold", action="store_true", help="overwrite generated scene skeletons")
    parser.add_argument("--skip-opus", action="store_true", help="keep existing ogg files")
    args = parser.parse_args(argv)

    payload = json.loads(SCENES_SRC.read_text(encoding="utf-8"))
    meta = payload["course"]
    scenes = [Scene(**scene) for scene in payload["scenes"]]
    total_count = len(scenes)
    print(f"course: {meta['title']} / {total_count} scenes")
    print(f"voice: {args.voice}  rate: {args.rate}")

    if args.no_tts:
        stale = [scene for scene in scenes if not cache_is_fresh(scene, args.voice, args.rate)]
        if stale:
            for scene in stale:
                print(
                    f"cache 缺失，或与当前 voice/rate/文本不一致：{scene.code} {scene.id}",
                    file=sys.stderr,
                )
            print("去掉 --no-tts 重新合成，或先清空 narration/cache/。", file=sys.stderr)
            return 1

    def prepare(scene: Scene) -> None:
        mp3, srt = cache_paths(scene)
        if not args.no_tts and not cache_is_fresh(scene, args.voice, args.rate):
            mp3.unlink(missing_ok=True)
            srt.unlink(missing_ok=True)
            run_tts(scene, args.voice, args.rate)
        scene.audio_file = f"{scene.code.lower()}-{scene.id}.ogg"
        ogg = AUDIO_DIR / scene.audio_file
        if args.skip_opus and ogg.is_file():
            import soundfile as sf

            info = sf.info(str(ogg))
            scene.audio_duration = info.frames / info.samplerate
        else:
            scene.audio_duration = transcode_to_opus(mp3, ogg)
        scene.cues = build_cues(scene, parse_srt(srt), args.lead)

    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        list(pool.map(prepare, scenes))

    write_cache_manifest(scenes, args.voice, args.rate)

    cursor = 0.0
    for scene in scenes:
        scene.start = round(cursor, 3)
        raw = args.lead + scene.audio_duration + args.tail
        scene.duration = math.ceil(raw * 100) / 100
        scene.audio_start = round(scene.start + args.lead, 3)
        cursor = scene.start + scene.duration
    total = round(cursor, 3)

    write_root(scenes, total)
    write_composition_course(scenes, meta)
    write_scene_skeletons(scenes, args.force_scaffold)
    patch_scene_captions(scenes)

    # Author-facing timing dump, including the cue table.
    timings = {
        "total": total,
        "voice": args.voice,
        "rate": args.rate,
        "scenes": [
            {
                "code": scene.code,
                "id": scene.id,
                "start": scene.start,
                "duration": scene.duration,
                "audioStart": scene.audio_start,
                "audioDuration": round(scene.audio_duration, 3),
                "narration": scene.narration,
                "cues": scene.cues,
            }
            for scene in scenes
        ],
    }
    (NARRATION_DIR / "timings.json").write_text(
        json.dumps(timings, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n"
    )

    # Scenes with cue table for scene authors (metadata + cues together).
    authored = json.loads(SCENES_SRC.read_text(encoding="utf-8"))
    authored["timings"] = {scene.id: {"start": scene.start, "duration": scene.duration, "cues": scene.cues} for scene in scenes}
    (NARRATION_DIR / "scenes.timed.json").write_text(
        json.dumps(authored, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n"
    )

    write_storyboard(scenes, total, args.voice, args.rate, args.lead, args.tail)
    print(f"total duration: {clock(total)} ({total:.2f}s)")
    print(f"audio: {len(scenes)} tracks -> {AUDIO_DIR}")
    for scene in scenes:
        print(f"  {scene.code} {scene.id:>20s} {scene.duration:6.2f}s  cues={len(scene.cues or []):2d}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
