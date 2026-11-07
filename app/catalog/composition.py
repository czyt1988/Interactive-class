"""Parse the root composition with ``html.parser``.

Only two things are read here: the root ``data-duration`` and the scene hosts
(any element carrying ``data-screen-id``). Scene files themselves are checked
by the resolver at file level; this module never interprets scene content.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path


class CompositionParseError(Exception):
    """A structured composition parse failure."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        field: str | None = None,
        screen_id: str | None = None,
        expected: str | None = None,
        line: int | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.field = field
        self.screen_id = screen_id
        self.expected = expected
        self.line = line


@dataclass(frozen=True)
class ScreenHost:
    screen_id: str
    element_id: str | None
    composition_id: str | None
    src: str | None
    start: float
    duration: float
    track_index: int | None
    width: int | None
    height: int | None
    line: int


@dataclass
class ParsedComposition:
    path: Path
    duration: float
    width: int | None = None
    height: int | None = None
    hosts: list[ScreenHost] = field(default_factory=list)


def _parse_float(
    raw: str | None,
    *,
    code: str,
    field_name: str,
    screen_id: str | None,
    line: int,
    allow_zero: bool,
) -> float:
    if raw is None or raw.strip() == "":
        raise CompositionParseError(
            code,
            f"缺少 {field_name}",
            field=field_name,
            screen_id=screen_id,
            expected="数字秒",
            line=line,
        )
    try:
        value = float(raw)
    except (TypeError, ValueError) as exc:
        raise CompositionParseError(
            code,
            f"{field_name}={raw!r} 不是数字",
            field=field_name,
            screen_id=screen_id,
            expected="数字秒",
            line=line,
        ) from exc
    if not math.isfinite(value) or value < 0 or (value == 0 and not allow_zero):
        requirement = "有限非负数" if allow_zero else "有限正数"
        raise CompositionParseError(
            code,
            f"{field_name}={raw!r} 不是{requirement}",
            field=field_name,
            screen_id=screen_id,
            expected=requirement,
            line=line,
        )
    return value


class _RootCompositionParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root_duration_raw: str | None = None
        self.root_found = False
        self.root_width: int | None = None
        self.root_height: int | None = None
        self.hosts: list[ScreenHost] = []
        self._host_errors: list[CompositionParseError] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        data = {name: value for name, value in attrs}
        line = self.getpos()[0]

        if tag == "div" and data.get("id") == "root" and not self.root_found:
            self.root_found = True
            self.root_duration_raw = data.get("data-duration")
            self.root_width = _optional_int(data.get("data-width"))
            self.root_height = _optional_int(data.get("data-height"))
            return

        if "data-screen-id" not in data:
            return

        screen_id = data.get("data-screen-id") or ""
        try:
            start = _parse_float(
                data.get("data-start"),
                code="host_start_invalid",
                field_name="data-start",
                screen_id=screen_id,
                line=line,
                allow_zero=True,
            )
            duration = _parse_float(
                data.get("data-duration"),
                code="host_duration_invalid",
                field_name="data-duration",
                screen_id=screen_id,
                line=line,
                allow_zero=False,
            )
        except CompositionParseError as exc:
            self._host_errors.append(exc)
            return

        self.hosts.append(
            ScreenHost(
                screen_id=screen_id,
                element_id=data.get("id"),
                composition_id=data.get("data-composition-id"),
                src=data.get("data-composition-src"),
                start=start,
                duration=duration,
                track_index=_optional_int(data.get("data-track-index")),
                width=_optional_int(data.get("data-width")),
                height=_optional_int(data.get("data-height")),
                line=line,
            )
        )

    def finish(self, path: Path) -> ParsedComposition:
        if self._host_errors:
            raise self._host_errors[0]
        if not self.root_found:
            raise CompositionParseError(
                "root_duration_missing",
                "根 composition 里找不到 id=root 的元素",
                field="data-duration",
                expected="<div id=\"root\" data-duration=\"…\">",
            )
        duration = _parse_float(
            self.root_duration_raw,
            code="root_duration_missing",
            field_name="data-duration",
            screen_id=None,
            line=1,
            allow_zero=False,
        )
        return ParsedComposition(
            path=path,
            duration=duration,
            width=self.root_width,
            height=self.root_height,
            hosts=self.hosts,
        )


def _optional_int(raw: str | None) -> int | None:
    if raw is None:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def parse_composition(path: Path) -> ParsedComposition:
    """Parse ``path`` and return its duration and scene hosts."""

    parser = _RootCompositionParser()
    parser.feed(path.read_text(encoding="utf-8"))
    parser.close()
    return parser.finish(path)
