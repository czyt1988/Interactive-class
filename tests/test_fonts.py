"""Font subsets and shell font wiring.

These two defects are invisible to request-level tests: the page still renders,
but individual glyphs swap to a system font (site) or the whole course shell
uses the wrong face (course). The checks read the committed subsets and the
built shell HTML directly.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from fontTools.ttLib import TTFont

from scripts import sync_runtime
from scripts.build_courses import build_course

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).parent / "fixtures" / "courses"
SLUG = "valid-two-screen"
APP_FONT = ROOT / "app" / "static" / "fonts" / "NotoSansSC-VF.woff2"
COURSE_FONT = (
    ROOT / "courses" / "ai-first-sees" / "composition" / "assets" / "fonts" / "NotoSansSC-VF.woff2"
)


def _covered(font_path: Path) -> set[str]:
    font = TTFont(str(font_path))
    return {chr(codepoint) for codepoint in font.getBestCmap()}


def _cjk(text: str) -> set[str]:
    return {char for char in text if ord(char) >= 0x2E80}


def test_site_font_covers_every_site_string() -> None:
    """Every character the site can print comes from the local subset.

    A subset that misses copy characters renders a heading in two typefaces at
    once (the browser falls back per glyph), which is what the homepage looked
    like before ``site_text()`` fed the subset.
    """

    missing = _cjk(sync_runtime.site_text()) - _covered(APP_FONT)
    assert not missing, "站点字体子集缺字，会回退到系统字体：" + "".join(sorted(missing))


def test_course_font_covers_the_shell_copy() -> None:
    assert COURSE_FONT.is_file(), "课程字体子集缺失，先运行 python scripts/sync_runtime.py"
    missing = _cjk(sync_runtime.shell_text()) - _covered(COURSE_FONT)
    assert not missing, "课程字体子集缺外壳文案用字：" + "".join(sorted(missing))


def _build_fixture_with_decoy_font(tmp_path: Path) -> Path:
    source = tmp_path / "courses" / SLUG
    shutil.copytree(FIXTURES / SLUG, source)
    fonts = source / "composition" / "assets" / "fonts"
    noto = fonts / "NotoSansSC-VF.woff2"
    # Sorts before "NotoSansSC-VF.woff2" on purpose: the shell must not take the
    # alphabetically first face, because a course ships mono faces next to Noto.
    (fonts / "AaaaMono-400.woff2").write_bytes(noto.read_bytes())
    result = build_course(source, out_root=tmp_path / "dist")
    assert result.ok, [error.message for error in result.errors]
    return result.output_dir


def test_course_shell_registers_the_noto_subset(tmp_path: Path) -> None:
    bundle = _build_fixture_with_decoy_font(tmp_path)
    html = (bundle / "index.html").read_text(encoding="utf-8")
    assert 'src: url("./composition/assets/fonts/NotoSansSC-VF.woff2")' in html
    assert "AaaaMono-400.woff2" not in html


def test_course_shell_localizes_the_level(tmp_path: Path) -> None:
    bundle = _build_fixture_with_decoy_font(tmp_path)
    html = (bundle / "index.html").read_text(encoding="utf-8")
    assert "<dt>级别</dt><dd>入门</dd>" in html


def test_font_subsetting_is_reproducible(tmp_path: Path) -> None:
    """Two identical syncs must produce identical bytes.

    fontTools stamps ``head.modified`` on save; without pinning it every
    ``python scripts/sync_runtime.py`` rewrote the committed fonts and changed
    the hashes in VERSION.json, leaving a dirty tree for a no-op sync.
    """

    source = ROOT / "design" / "fonts" / "NotoSansSC-VF.ttf"
    first = tmp_path / "first.woff2"
    second = tmp_path / "second.woff2"
    sync_runtime.subset_font(source, first, extra_text="首页文案")
    sync_runtime.subset_font(source, second, extra_text="首页文案")
    assert first.read_bytes() == second.read_bytes()
