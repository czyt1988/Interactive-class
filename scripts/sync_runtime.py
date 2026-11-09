"""Copy pinned vendor assets into the runtime and course template.

Sources come from ``tools/node_modules`` (authoring-only, never shipped) and
``design/``. Outputs land in ``runtime/vendor``, ``courses/_template`` and
``app/static``. Every copied file is hashed into ``runtime/VERSION.json`` so a
stale bundle is visible without opening the course.

Run with: ``python scripts/sync_runtime.py``
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOOLS = ROOT / "tools" / "node_modules"
RUNTIME = ROOT / "runtime"
DESIGN = ROOT / "design"
APP_STATIC = ROOT / "app" / "static"
TEMPLATE_ASSETS = ROOT / "courses" / "_template" / "composition" / "assets"
COURSE_ROOT = ROOT / "courses"

# Subset covering common Chinese text plus punctuation and latin/digits.
# Kept as a literal so the subset is reproducible without external lists.
SUBSET_TEXT = (
    "的一是不了在人有我他这中大来上国个到说们为子和你地出道也时年得就那要下以生会自着"
    "去之过家学对可她里后小么心多天而能好都然没日于起还发成事只作当想看文无开手十用主"
    "行方又如前所本见经头面公同三已老从动两长知民样现分将外但身些与高意进把法此实回二"
    "理美点月明其种声全工己话儿者向情部正名定女问力机给等几很业最间新什打便位因重被走"
    "电四第门相次东政海口使教西再平真听世气信北少关并内加化由却代军产入先山五太水万市"
    "眼体别处总才场师书比住员九笑性通目华报立马命张活难神数件安表原车白应路期叫死常提"
    "感金何更反合放做系计或司利受光王果亲界及今京务制解各任至清物台象记边共风战干接它"
    "许八特觉望直服毛林题建南度统色字请交爱让认算论百吃义科怎元社术结六功指思非流每青"
    "管夫连远资队跟带花快条院变联言权往展该领传近留红治决周保达办运武半候七必城父强步"
    "完革深区即求品士转量空甚众技轻程告江语英基派满式李息写呢识极令黄德收脸钱党倒未持"
    "取设始版双历越史商千片容研像找友孩站广改议形委早房音火际则首单据导影失拿网香似斯"
    "专石若兵弟谁校读志飞观争究包组造落视济喜离虽坐集编宝谈府拉黑且随格尽剑讲布杀微怕"
    "母调局根曾准团段终乐切级克精哪官示冷域玉跟吗吧啊哦嗯唉呀嘛哈嘿喂诶哇哼呗咳哦噢"
    "，。、；：？！“”‘’（）《》〈〉…—～·「」『』【】〔〕　 "
    "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
    " -.+_/&%#@*()[]{}<>|\\\"'`:;,!?=^~$"
    "→←↑↓×÷±≈≠≤≥∞∑√°%‰§¶†‡•…‰€£¥©®™°′″"
)

GSAP_FILES = ("gsap.min.js",)
PLAYER_FILES = ("hyperframes-player.global.js", "hyperframe.runtime.iife.js")

# The deck shell (course-deck.js/.css, shell.html.j2) is versioned separately from
# the pinned vendor runtime. Bump this whenever the shell or its CSS changes.
DECK_VERSION = "1.3.0"


class SyncError(Exception):
    pass


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def require(path: Path, hint: str) -> Path:
    if not path.exists():
        raise SyncError(f"缺少 {path}\n  → {hint}")
    return path


def copy(src: Path, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)
    return dest


def course_text(course_dir: Path) -> str:
    """All display text of one course, so its font subset covers the real copy."""
    parts: list[str] = []
    manifest = course_dir / "course.json"
    if manifest.is_file():
        parts.append(manifest.read_text(encoding="utf-8"))
    composition = course_dir / "composition"
    if composition.is_dir():
        for path in sorted(composition.rglob("*")):
            if path.is_file() and path.suffix.lower() in {".html", ".htm", ".json"}:
                parts.append(path.read_text(encoding="utf-8", errors="ignore"))
    return "".join(parts)


def subset_font(
    source: Path,
    target: Path,
    *,
    max_bytes: int = 2 * 1024 * 1024,
    extra_text: str = "",
) -> Path:
    """Subset the variable font to the characters we actually ship."""
    if (
        target.exists()
        and target.stat().st_size <= max_bytes
        and target.stat().st_mtime >= source.stat().st_mtime
        and not extra_text.strip()
    ):
        return target
    from fontTools import subset
    from fontTools.ttLib import TTFont

    unique = "".join(dict.fromkeys(SUBSET_TEXT + extra_text))
    target.parent.mkdir(parents=True, exist_ok=True)
    options = subset.Options()
    options.flavor = "woff2"
    options.layout_features = ["*"]
    options.name_IDs = ["*"]
    options.notdef_outline = True
    options.hinting = False
    options.desubroutinize = True
    font = TTFont(str(source))
    subsetter = subset.Subsetter(options=options)
    subsetter.populate(text=unique)
    subsetter.subset(font)
    font.flavor = "woff2"
    font.save(str(target))

    if target.stat().st_size > max_bytes:
        raise SyncError(
            f"字体子集 {target.stat().st_size} 字节，超过预算 {max_bytes}；"
            "请缩小 SUBSET_TEXT 或压缩"
        )
    return target


def sync_vendor() -> dict[str, dict[str, str]]:
    hyperframes_dist = TOOLS / "hyperframes" / "dist"
    gsap_dist = TOOLS / "gsap" / "dist"
    require(hyperframes_dist / "hyperframes-player.global.js", "cd tools && npm install")
    require(gsap_dist / "gsap.min.js", "cd tools && npm install")

    hashes: dict[str, dict[str, str]] = {"vendor": {}, "gsap": {}, "fonts": {}}

    vendor_target = RUNTIME / "vendor"
    for name in PLAYER_FILES:
        source = require(hyperframes_dist / name, "cd tools && npm install")
        copy(source, vendor_target / name)
        hashes["vendor"][name] = sha256(vendor_target / name)

    for name in GSAP_FILES:
        source = require(gsap_dist / name, "cd tools && npm install")
        for target in (TEMPLATE_ASSETS / "vendor" / name, vendor_target / name):
            copy(source, target)
            hashes["gsap"][f"{target.relative_to(ROOT).as_posix()}"] = sha256(target)

    # Every real course gets the same pinned vendor files.
    for course_dir in sorted(COURSE_ROOT.iterdir()) if COURSE_ROOT.is_dir() else []:
        if not course_dir.is_dir() or course_dir.name.startswith((".", "_")):
            continue
        assets = course_dir / "composition" / "assets"
        if not assets.is_dir():
            continue
        vendor = assets / "vendor"
        for name in GSAP_FILES:
            copy(gsap_dist / name, vendor / name)
            hashes["gsap"][f"{vendor.relative_to(ROOT).as_posix()}/{name}"] = sha256(vendor / name)

    return hashes


def sync_fonts() -> dict[str, str]:
    source = require(DESIGN / "fonts" / "NotoSansSC-VF.ttf", "见 design/README.md 的字体下载步骤")
    hashes: dict[str, str] = {}
    for target in (
        TEMPLATE_ASSETS / "fonts" / "NotoSansSC-VF.woff2",
        APP_STATIC / "fonts" / "NotoSansSC-VF.woff2",
    ):
        subset_font(source, target)
        hashes[target.relative_to(ROOT).as_posix()] = sha256(target)

    for course_dir in sorted(COURSE_ROOT.iterdir()) if COURSE_ROOT.is_dir() else []:
        if not course_dir.is_dir() or course_dir.name.startswith((".", "_")):
            continue
        assets = course_dir / "composition" / "assets"
        if (assets / "course.css").is_file():
            target = assets / "fonts" / "NotoSansSC-VF.woff2"
            subset_font(source, target, extra_text=course_text(course_dir))
            hashes[target.relative_to(ROOT).as_posix()] = sha256(target)
    return hashes


def sync_tokens() -> dict[str, str]:
    tokens = require(DESIGN / "tokens.css", "缺少 design/tokens.css")
    hashes: dict[str, str] = {}
    for target in (RUNTIME / "tokens.css", APP_STATIC / "tokens.css"):
        copy(tokens, target)
        hashes[target.relative_to(ROOT).as_posix()] = sha256(target)
    return hashes


def write_version(vendor: dict[str, dict[str, str]], fonts: dict[str, str], tokens: dict[str, str]) -> None:
    tools_package = json.loads((ROOT / "tools" / "package.json").read_text(encoding="utf-8"))
    versions = tools_package["dependencies"]
    payload = {
        "schemaVersion": 1,
        "hyperframes": versions["hyperframes"],
        "gsap": versions["gsap"],
        "player": PLAYER_FILES[0],
        "runtime": PLAYER_FILES[1],
        "deckVersion": DECK_VERSION,
        "fonts": fonts,
        "tokens": tokens,
        "files": vendor,
    }
    (RUNTIME / "VERSION.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="同步播放器运行时、GSAP、字体和设计令牌")
    parser.add_argument("--skip-fonts", action="store_true", help="跳过字体子集（较慢）")
    args = parser.parse_args(argv)

    try:
        vendor = sync_vendor()
        tokens = sync_tokens()
        fonts = {} if args.skip_fonts else sync_fonts()
    except SyncError as exc:
        print(f"同步失败：{exc}", file=sys.stderr)
        return 1
    write_version(vendor, fonts, tokens)

    player = RUNTIME / "vendor" / PLAYER_FILES[0]
    runtime = RUNTIME / "vendor" / PLAYER_FILES[1]
    print(f"player   {player.stat().st_size:>9,} B  runtime/vendor/{PLAYER_FILES[0]}")
    print(f"runtime  {runtime.stat().st_size:>9,} B  runtime/vendor/{PLAYER_FILES[1]}")
    for name, digest in list(fonts.items()):
        size = (ROOT / name).stat().st_size
        print(f"font     {size:>9,} B  {name}  {digest[:12]}")
    print("版本已写入 runtime/VERSION.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
