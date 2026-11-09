"""Copy the curated outline material into the course package, compressed.

The director script (``大纲/AI-Agent-入门课/02-逐页脚本.md``) asks for real product
logos, real UI screenshots and real photos as evidence. This script is the only
place those files enter ``courses/ai-first-sees/composition/assets/media``:

- logos: trim transparent padding, cap at 256 px, keep brand colour;
- screenshots: RGB WebP, max 1280 px wide, quality 80 (card evidence, not a
  background), hard cap 420 KB per file;
- photos: WebP, max 1000 px on the long side.

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
SOURCE = ROOT / "大纲" / "AI-Agent-入门课" / "素材"
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
    "workbuddy": "screenshot/workbuddy.png",
    "dsh-desktop": "screenshot/dsh-desktop.png",
    "dsh-plugins": "screenshot/dsh-plugins.png",
    "agents-md-site": "screenshot/agents-md-site.png",
    "claude-code-permission": "screenshot/claude-code-permission.png",
}

MAX_LOGO_PX = 256
MAX_SHOT_WIDTH = 1280
MAX_SHOT_BYTES = 420 * 1024
MAX_PHOTO_PX = 1000


def _save_webp(image: Image.Image, path: Path, quality: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image.convert("RGB").save(path, "WEBP", quality=quality, method=6)


def prepare_logo(name: str, relative: str) -> None:
    image = Image.open(SOURCE / relative).convert("RGBA")
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
    image = Image.open(SOURCE / relative).convert("RGB")
    if max(image.size) > MAX_PHOTO_PX:
        image.thumbnail((MAX_PHOTO_PX, MAX_PHOTO_PX), Image.LANCZOS)
    _save_webp(image, TARGET / "photo" / f"{name}.webp", 84)


def prepare_screenshot(name: str, relative: str) -> None:
    image = Image.open(SOURCE / relative).convert("RGB")
    if image.width > MAX_SHOT_WIDTH:
        height = round(image.height * MAX_SHOT_WIDTH / image.width)
        image = image.resize((MAX_SHOT_WIDTH, height), Image.LANCZOS)
    target = TARGET / "shot" / f"{name}.webp"
    _save_webp(image, target, 80)
    quality = 80
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
        prepare_screenshot(name, relative)

    total = sum(path.stat().st_size for path in TARGET.rglob("*") if path.is_file())
    print(f"media -> {TARGET}")
    for folder in ("logo", "photo", "shot"):
        files = sorted((TARGET / folder).glob("*"))
        size = sum(path.stat().st_size for path in files) / 1024
        print(f"  {folder:5s} {len(files):2d} files {size:7.1f} KB")
    print(f"  total {total / 1024 / 1024:.2f} MB")


if __name__ == "__main__":
    main()
