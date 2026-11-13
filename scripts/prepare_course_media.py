"""Copy the curated outline material into the course package, compressed.

The course outline (``courses-outline/ai-first-sees/outline.md``) asks for real
product logos, real UI screenshots, real photos and official model samples as
evidence. This script is the only place those files enter
``courses/ai-first-sees/composition/assets/media``:

- logos: trim transparent padding, cap at 256 px, keep brand colour;
- screenshots: RGB WebP, max 1280 px wide, quality 80 (card evidence, not a
  background), hard cap 420 KB per file;
- cropped trace strips (S22): crop the band that carries the meaning, resize to
  1400x380 (twice the 700x190 evidence card) so interface text stays crisp;
- photos: WebP, max 1000 px on the long side;
- generated samples (``gen/``): official image / video-model examples, same
  rules as screenshots.

Source tree: ``courses-outline/ai-first-sees/素材`` (the old ``大纲/`` tree was
migrated away). The original downloads for S01-S20 were never tracked by git and
were lost together with that directory: for those entries the source file is
missing. This script then prints a warning and leaves the already committed
``composition/assets/media`` file untouched, so a full rebuild only rewrites what
can still be reproduced. The media files committed under
``courses/ai-first-sees/composition/assets/media`` are the source of truth for
S01-S20; the S21-S27 material added in this round is fully reproducible from
``素材/``.

It never touches ``素材/`` itself and is safe to re-run. Run it with a Python
that has Pillow (the bundled authoring runtime), then rebuild the course:

    python scripts/prepare_course_media.py
    python scripts/build_narration.py --no-tts --skip-opus
    python scripts/build_courses.py --course ai-first-sees
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "courses-outline" / "ai-first-sees" / "素材"
TARGET = ROOT / "courses" / "ai-first-sees" / "composition" / "assets" / "media"

LOGOS = {
    "deepmind": "logo/deepmind.png",
    "chatgpt": "logo/chatgpt.png",
    "openai": "logo/openai.png",
    "cursor": "logo/cursor.png",
    "claude": "logo/claude.png",
    "codex": "logo/codex.png",
    "opencode": "logo/opencode.png",
    "autogpt": "logo/autogpt.png",
    "devin": "logo/devin.png",
    "openclaw": "logo/openclaw.png",
    "trae": "logo/trae.png",
    "qwen": "logo/qwen.png",
    "qoder": "logo/qoder.png",
    "kimi": "logo/kimi.png",
    "zcode": "logo/zcode.png",
    "codebuddy": "logo/codebuddy.png",
    "workbuddy": "logo/workbuddy.png",
    "deepseek": "logo/deepseek.png",
    "dsh": "logo/dsh.png",
    "coze": "logo/coze.png",
    "dify": "logo/dify.png",
    "n8n": "logo/n8n.png",
    "mcp": "logo/mcp.png",
}

# White-background wordmarks / icons: knock the paper-white out so they sit on
# the course paper. The value is the per-channel threshold above which a pixel
# is treated as background.
WHITE_BG_LOGOS = {"dify": 244, "n8n": 244, "dsh": 238}

PHOTOS = {
    "alphago-lee-sedol": "photo/alphago-lee-sedol.webp",
    "alphago-ke-jie": "photo/alphago-ke-jie.jpg",
    "cat": "photo/cat.jpg",
}

SCREENSHOTS = {
    # S01-S20 (sources lost with the 大纲/ migration, kept as committed media)
    "chatgpt-ui": "screenshot/chatgpt-ui.png",
    "cursor-agent-mode": "screenshot/cursor-agent-mode.png",
    "claude-code-terminal": "screenshot/claude-code-terminal.png",
    "codex-cloud": "screenshot/codex-cloud.png",
    "opencode-tui": "screenshot/opencode-tui.png",
    "devin-ui": "screenshot/devin-ui.png",
    "coze-workflow": "screenshot/coze-workflow.png",
    "dify-workflow": "screenshot/dify-workflow.png",
    "n8n-workflow": "screenshot/n8n-workflow.png",
    "trae-ide": "screenshot/trae-ide.png",
    "qwen-code-terminal": "screenshot/qwen-code-terminal.png",
    "kimi-code": "screenshot/kimi-code.png",
    "zcode": "screenshot/zcode.png",
    "qoder": "screenshot/qoder.png",
    "workbuddy": "screenshot/workbuddy.png",
    "dsh-desktop": "screenshot/dsh-desktop.png",
    "dsh-plugins": "screenshot/dsh-plugins.png",
    "agents-md-site": "screenshot/agents-md-site.png",
    "claude-code-permission": "screenshot/claude-code-permission.png",
    # S21-S27 (reproducible from 素材/)
    "dsh-skills": "screenshot/dsh-skills.webp",
    "dsh-slash": "screenshot/dsh-slash-input.webp",
    "superpowers-star": "screenshot/superpowers-star-history.png",
    "huashu-ppt": "screenshot/huashu-case-qianli-pages.jpg",
    "huashu-ppt-science": "screenshot/huashu-case-blackhole-pages.jpg",
}

# S22 evidence strips: the DSH trace panel is shown as three wide cards, each
# cropped to the band that carries the meaning (selected trace row on the left,
# detail panel on the right) and encoded at twice the 700x190 card size so the
# interface text stays crisp on the 1920x1080 canvas.
CROPPED_SHOTS = {
    "dsh-trace-system": ("screenshot/dsh-系统提示词.png", (0, 158, 989, 428)),
    "dsh-trace-user": ("screenshot/dsh-用户输入.png", (0, 165, 1004, 435)),
    "dsh-trace-agentsmd": ("screenshot/dsh-读取项目Agents.md.png", (0, 205, 1002, 475)),
}
CROP_TARGET_SIZE = (1400, 380)

# Official image / video model samples (S24). Video files are not kept, only a
# representative still extracted with ffmpeg from the official release video.
GEN = {
    "seedream-sample": "gen/seedream-sample.webp",
    "gpt-image-sample": "gen/gpt-image-sample.png",
    "seedance-still": "gen/seedance-still.jpg",
    "kling-still": "gen/kling-still.jpg",
}

# Entries added for S21-S27 must be reproducible; missing source is fatal.
REQUIRED_SOURCES = {
    "screenshot/dsh-系统提示词.png",
    "screenshot/dsh-用户输入.png",
    "screenshot/dsh-读取项目Agents.md.png",
    "screenshot/dsh-skills.webp",
    "screenshot/dsh-slash-input.webp",
    "screenshot/superpowers-star-history.png",
    "screenshot/huashu-case-qianli-pages.jpg",
    "screenshot/huashu-case-blackhole-pages.jpg",
    *GEN.values(),
}

MAX_LOGO_PX = 256
MAX_SHOT_WIDTH = 1280
MAX_SHOT_BYTES = 420 * 1024
MAX_PHOTO_PX = 1000

MISSING_SOURCES: list[str] = []


def _resolve(relative: str) -> Path | None:
    path = SOURCE / relative
    if path.exists():
        return path
    if relative in REQUIRED_SOURCES:
        raise SystemExit(f"required source is missing: {path}")
    MISSING_SOURCES.append(relative)
    return None


def _save_webp(image: Image.Image, path: Path, quality: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image.convert("RGB").save(path, "WEBP", quality=quality, method=6)


def prepare_logo(name: str, relative: str) -> None:
    source = _resolve(relative)
    if source is None:
        return
    image = Image.open(source).convert("RGBA")
    if name in WHITE_BG_LOGOS:
        threshold = WHITE_BG_LOGOS[name]
        pixels = image.load()
        for y in range(image.height):
            for x in range(image.width):
                r, g, b, a = pixels[x, y]
                if a and r > threshold and g > threshold and b > threshold:
                    pixels[x, y] = (r, g, b, 0)
    bbox = image.getchannel("A").getbbox()
    if bbox:
        image = image.crop(bbox)
    if max(image.size) > MAX_LOGO_PX:
        image.thumbnail((MAX_LOGO_PX, MAX_LOGO_PX), Image.LANCZOS)
    target = TARGET / "logo" / f"{name}.png"
    target.parent.mkdir(parents=True, exist_ok=True)
    image.save(target, "PNG", optimize=True)


def prepare_photo(name: str, relative: str) -> None:
    source = _resolve(relative)
    if source is None:
        return
    image = Image.open(source).convert("RGB")
    if max(image.size) > MAX_PHOTO_PX:
        image.thumbnail((MAX_PHOTO_PX, MAX_PHOTO_PX), Image.LANCZOS)
    _save_webp(image, TARGET / "photo" / f"{name}.webp", 84)


def prepare_compressed(name: str, relative: str, folder: str, quality: int = 80) -> None:
    """Resize to max 1280 px wide, encode WebP, shrink quality until under cap."""
    source = _resolve(relative)
    if source is None:
        return
    image = Image.open(source).convert("RGB")
    if image.width > MAX_SHOT_WIDTH:
        height = round(image.height * MAX_SHOT_WIDTH / image.width)
        image = image.resize((MAX_SHOT_WIDTH, height), Image.LANCZOS)
    target = TARGET / folder / f"{name}.webp"
    _save_webp(image, target, quality)
    while target.stat().st_size > MAX_SHOT_BYTES and quality > 45:
        quality -= 8
        _save_webp(image, target, quality)
    if target.stat().st_size > MAX_SHOT_BYTES:
        raise SystemExit(f"{name}: still {target.stat().st_size} bytes at quality {quality}")


def prepare_cropped(name: str, relative: str, box: tuple[int, int, int, int]) -> None:
    """Crop one meaningful band out of a screenshot, encode at 2x card size."""
    source = _resolve(relative)
    if source is None:
        return
    image = Image.open(source).convert("RGB").crop(box)
    image = image.resize(CROP_TARGET_SIZE, Image.LANCZOS)
    target = TARGET / "shot" / f"{name}.webp"
    quality = 85
    _save_webp(image, target, quality)
    while target.stat().st_size > MAX_SHOT_BYTES and quality > 45:
        quality -= 8
        _save_webp(image, target, quality)
    if target.stat().st_size > MAX_SHOT_BYTES:
        raise SystemExit(f"{name}: still {target.stat().st_size} bytes at quality {quality}")


def main() -> None:
    for name, relative in LOGOS.items():
        prepare_logo(name, relative)
    for name, relative in PHOTOS.items():
        prepare_photo(name, relative)
    for name, relative in SCREENSHOTS.items():
        prepare_compressed(name, relative, "shot")
    for name, (relative, box) in CROPPED_SHOTS.items():
        prepare_cropped(name, relative, box)
    for name, relative in GEN.items():
        prepare_compressed(name, relative, "gen", quality=82)

    if MISSING_SOURCES:
        print(
            f"{len(MISSING_SOURCES)} legacy source file(s) missing from {SOURCE}; "
            "kept the committed media file instead:"
        )
        for relative in MISSING_SOURCES:
            print(f"  keep  {relative}")

    total = sum(path.stat().st_size for path in TARGET.rglob("*") if path.is_file())
    print(f"media -> {TARGET}")
    for folder in ("logo", "photo", "shot", "gen"):
        files = sorted((TARGET / folder).glob("*"))
        size = sum(path.stat().st_size for path in files) / 1024
        print(f"  {folder:5s} {len(files):2d} files {size:7.1f} KB")
    print(f"  total {total / 1024 / 1024:.2f} MB")


if __name__ == "__main__":
    main()
