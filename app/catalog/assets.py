"""Static asset auditing for course compositions.

The builder uses this module to prove a course bundle has no external resource
loads, no absolute paths, and no real-clock animation sources. Only things that
actually fetch over the network are flagged; ordinary ``<a href>`` citations
are allowed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

RESOURCE_ATTRS: dict[str, tuple[str, ...]] = {
    "script": ("src",),
    "link": ("href",),
    "img": ("src", "srcset"),
    "source": ("src", "srcset"),
    "video": ("src", "poster"),
    "audio": ("src",),
    "iframe": ("src",),
    "embed": ("src",),
    "object": ("data",),
    "track": ("src",),
    "input": ("src",),
}

LINK_RESOURCE_RELS = {"stylesheet", "preload", "modulepreload", "icon", "apple-touch-icon"}

CSS_URL_RE = re.compile(r"url\(\s*(?P<quote>['\"]?)(?P<url>[^'\")]+)(?P=quote)\s*\)", re.IGNORECASE)
CSS_IMPORT_RE = re.compile(r"@import\s+(?:url\(\s*)?['\"]?(?P<url>[^'\")\s;]+)", re.IGNORECASE)
CSS_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)
FORBIDDEN_CLOCKS = (
    ("Date.now(", "Date.now()"),
    ("setInterval(", "setInterval()"),
    ("Math.random(", "Math.random()"),
)


@dataclass(frozen=True)
class AssetIssue:
    code: str
    message: str
    file: str
    field: str
    value: str
    screen_id: str | None = None
    line: int | None = None


class _ResourceParser(HTMLParser):
    def __init__(self, path: Path) -> None:
        super().__init__(convert_charrefs=True)
        self.path = path
        self.resources: list[tuple[str, str, int]] = []
        self.styles: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        data = {name.lower(): value or "" for name, value in attrs}
        line = self.getpos()[0]
        if tag == "link":
            rels = set(data.get("rel", "").lower().split())
            if rels & LINK_RESOURCE_RELS:
                self.resources.append(("link[href]", data.get("href", ""), line))
        for attribute in RESOURCE_ATTRS.get(tag, ()):
            value = data.get(attribute)
            if value:
                self.resources.append((f"{tag}[{attribute}]", value, line))
        if data.get("style"):
            self.styles.append(data["style"])

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)

    def handle_data(self, data: str) -> None:
        if self.lasttag == "style":
            self.styles.append(data)


def _is_external(value: str) -> bool:
    lowered = value.strip().lower()
    return lowered.startswith(("http://", "https://", "//"))


def _is_allowed_nonfile(value: str) -> bool:
    lowered = value.strip().lower()
    return lowered.startswith(("data:", "#", "mailto:", "tel:", "blob:"))


def _check_reference(
    value: str,
    *,
    root: Path,
    base: Path,
    file: Path,
    field: str,
    line: int | None = None,
) -> AssetIssue | None:
    raw = value.strip()
    if not raw or _is_allowed_nonfile(raw):
        return None
    if _is_external(raw):
        return AssetIssue(
            "external_asset",
            f"外部资源加载被拒绝：{raw}",
            file=str(file),
            field=field,
            value=raw,
            line=line,
        )
    if raw.startswith("/"):
        return AssetIssue(
            "absolute_asset_path",
            f"资源路径不能以 / 开头：{raw}",
            file=str(file),
            field=field,
            value=raw,
            line=line,
        )
    path_part = unquote(urlsplit(raw).path)
    if not path_part:
        return None
    candidate = (base / path_part).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError:
        return AssetIssue(
            "asset_outside_bundle",
            f"资源路径逃出了课程包：{raw}",
            file=str(file),
            field=field,
            value=raw,
            line=line,
        )
    if not candidate.is_file():
        return AssetIssue(
            "asset_missing",
            f"资源文件不存在：{raw}",
            file=str(file),
            field=field,
            value=raw,
            line=line,
        )
    return None


def _split_srcset(value: str) -> list[str]:
    candidates: list[str] = []
    for part in value.split(","):
        url = part.strip().split(" ")[0]
        if url:
            candidates.append(url)
    return candidates


def _scan_html(path: Path, root: Path) -> list[AssetIssue]:
    parser = _ResourceParser(path)
    parser.feed(path.read_text(encoding="utf-8"))
    issues: list[AssetIssue] = []
    for field, value, line in parser.resources:
        values = _split_srcset(value) if field.endswith("[srcset]") else [value]
        for item in values:
            issue = _check_reference(
                item, root=root, base=root, file=path, field=field, line=line
            )
            if issue:
                issues.append(issue)
    for css in parser.styles:
        issues.extend(_scan_css_text(css, path=path, root=root, base=root, offset=0))
    return issues


def _scan_css_text(
    css: str, *, path: Path, root: Path, base: Path, offset: int = 0
) -> list[AssetIssue]:
    cleaned = CSS_COMMENT_RE.sub(lambda match: "\n" * match.group(0).count("\n"), css)
    issues: list[AssetIssue] = []
    for match in CSS_IMPORT_RE.finditer(cleaned):
        issue = _check_reference(
            match.group("url"),
            root=root,
            base=base,
            file=path,
            field="@import",
            line=cleaned[: match.start()].count("\n") + 1 + offset,
        )
        if issue:
            issues.append(issue)
    for match in CSS_URL_RE.finditer(cleaned):
        issue = _check_reference(
            match.group("url"),
            root=root,
            base=base,
            file=path,
            field="css url()",
            line=cleaned[: match.start()].count("\n") + 1 + offset,
        )
        if issue:
            issues.append(issue)
    return issues


def scan_composition(root: Path, *, skip_vendor: bool = True) -> list[AssetIssue]:
    """Return every external/missing/absolute resource reference in ``root``."""

    issues: list[AssetIssue] = []
    vendor = (root / "assets" / "vendor").resolve()
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if skip_vendor and vendor in path.resolve().parents:
            continue
        suffix = path.suffix.lower()
        if suffix in {".html", ".htm"}:
            issues.extend(_scan_html(path, root))
        elif suffix in {".css", ".js", ".mjs"}:
            text = path.read_text(encoding="utf-8", errors="replace")
            if suffix == ".css":
                issues.extend(_scan_css_text(text, path=path, root=root, base=path.parent))
            for needle, label in FORBIDDEN_CLOCKS:
                if needle in text:
                    issues.append(
                        AssetIssue(
                            "forbidden_clock",
                            f"动画时钟不允许使用 {label}",
                            file=str(path),
                            field=label,
                            value=needle,
                        )
                    )
    return issues
