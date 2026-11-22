"""Documentation is a navigation surface: relative links must resolve.

README is the entry point and docs/README.md is the map. A moved file with a
stale link is worse than no link, so keep this part mechanical.
"""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parent.parent
LINK_RE = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
EXTERNAL_PREFIXES = ("http://", "https://", "mailto:", "#")


def _documents() -> list[Path]:
    return [ROOT / "README.md", *sorted((ROOT / "docs").rglob("*.md"))]


def test_relative_links_resolve() -> None:
    missing: list[str] = []

    for document in _documents():
        for raw_target in LINK_RE.findall(document.read_text(encoding="utf-8")):
            target = raw_target.strip()
            if target.startswith("<") and target.endswith(">"):
                target = target[1:-1]
            if target.startswith(EXTERNAL_PREFIXES):
                continue

            relative = unquote(target.split("#", 1)[0])
            if relative and not (document.parent / relative).exists():
                missing.append(f"{document.relative_to(ROOT).as_posix()} -> {target}")

    assert not missing, "broken relative links:\n" + "\n".join(missing)
