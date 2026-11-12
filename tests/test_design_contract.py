"""Mechanical checks for the front-end design contract in DESIGN.md.

The contract is a document first, but a few of its rules can be enforced without
a browser: token sync, token contrast, no em-dashes in UI copy, and the eyebrow
budget on the homepage. Keep this file small; visual judgment stays in review.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEMPLATES = ROOT / "app" / "templates"
RUNTIME = ROOT / "runtime"

EM_DASH = "\u2014"
EN_DASH = "\u2013"

TOKEN_RE = re.compile(r"(--[a-z0-9-]+):\s*([^;]+);")


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _tokens() -> dict[str, str]:
    return {name: value.strip() for name, value in TOKEN_RE.findall(_read(ROOT / "design" / "tokens.css"))}


def _hex(value: str) -> str:
    match = re.search(r"#[0-9a-fA-F]{6}", value)
    assert match, f"not a hex colour: {value}"
    return match.group(0)


def _relative_luminance(colour: str) -> float:
    digits = colour.lstrip("#")
    channels = [int(digits[index : index + 2], 16) / 255 for index in (0, 2, 4)]

    def linear(channel: float) -> float:
        return channel / 12.92 if channel <= 0.03928 else ((channel + 0.055) / 1.055) ** 2.4

    red, green, blue = (linear(value) for value in channels)
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def _contrast(foreground: str, background: str) -> float:
    lighter, darker = sorted(
        (_relative_luminance(foreground), _relative_luminance(background)), reverse=True
    )
    return (lighter + 0.05) / (darker + 0.05)


def test_design_md_is_the_referenced_contract() -> None:
    design = ROOT / "DESIGN.md"
    assert design.is_file(), "DESIGN.md is missing"
    assert "DESIGN.md" in _read(ROOT / "AGENTS.md"), "AGENTS.md must point agents at DESIGN.md"
    assert "DESIGN.md" in _read(ROOT / "README.md")


def test_tokens_are_synced_from_the_single_source() -> None:
    source = _read(ROOT / "design" / "tokens.css")
    assert source == _read(ROOT / "app" / "static" / "tokens.css")
    assert source == _read(ROOT / "runtime" / "tokens.css")


def test_contract_tokens_exist() -> None:
    tokens = _tokens()
    required = (
        "--paper",
        "--paper-raised",
        "--paper-deep",
        "--ink",
        "--ink-soft",
        "--ink-faint",
        "--line",
        "--line-strong",
        "--accent",
        "--accent-text",
        "--accent-soft",
        "--accent-ink",
        "--font-sans",
        "--font-mono",
        "--maxw",
        "--gutter",
        "--radius-inline",
        "--radius-mini",
        "--radius-stage",
        "--radius-card",
        "--radius-poster",
        "--radius-pill",
        "--shadow-card",
        "--ease",
        "--z-header",
        "--z-drawer",
        "--z-skip",
    )
    for token in required:
        assert token in tokens, f"DESIGN.md promises {token}, tokens.css does not define it"


def test_text_tokens_pass_wcag_aa_on_paper_surfaces() -> None:
    tokens = _tokens()
    text_tokens = ("--ink", "--ink-soft", "--ink-faint", "--accent-text")
    surfaces = ("--paper", "--paper-raised", "--paper-deep")
    for text in text_tokens:
        for surface in surfaces:
            ratio = _contrast(_hex(tokens[text]), _hex(tokens[surface]))
            assert ratio >= 4.5, f"{text} on {surface} is {ratio:.2f}:1, below WCAG AA"


def test_ui_templates_have_no_em_dash() -> None:
    templates = [*TEMPLATES.rglob("*.html"), *RUNTIME.glob("*.j2")]
    assert templates
    for path in templates:
        text = _read(path)
        assert EM_DASH not in text, f"{path}: em-dash is banned in UI copy (DESIGN.md 7.2)"
        assert EN_DASH not in text, f"{path}: use a hyphen for ranges, not an en-dash (DESIGN.md 7.2)"


def test_homepage_respects_the_eyebrow_budget() -> None:
    home = _read(TEMPLATES / "home.html")
    assert home.count('class="eyebrow"') <= 1, "homepage allows at most one eyebrow (DESIGN.md 4.2)"


def test_scroll_reveal_keeps_content_visible() -> None:
    """The homepage reveal must not hide content in renders that never scroll.

    A full-page capture, a preview panel or an export paints the document at
    scroll position 0; fading in from opacity 0 with a backwards fill turned
    everything below the hero into blank paper there (DESIGN.md 6.2).
    """

    home_css = _read(ROOT / "app" / "static" / "home.css")
    start = home_css.index("@supports (animation-timeline: view())")
    block = home_css[start:]
    assert "animation: slide-up linear;" in block
    assert "rise-in" not in block, "滚动显现在用淡入关键帧，会让未滚动到的内容不可见"
    assert "both" not in block, "滚动显现不能带 backwards fill"


def test_design_decisions_are_recorded() -> None:
    design = _read(ROOT / "DESIGN.md")
    for section in ("## 0. 设计阅读", "## 3. 令牌", "## 4. 版式系统", "## 13. 交付前自检", "## 14. 决策记录"):
        assert section in design, f"DESIGN.md lost required section: {section}"
