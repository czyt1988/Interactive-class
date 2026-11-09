"""Human-readable formatting shared by templates and the admin page.

Chinese copy is the product language, so durations, byte sizes and timestamps
are formatted here once instead of being re-invented in templates or routes.
"""

from __future__ import annotations

from datetime import UTC, datetime


def format_duration(seconds: float) -> str:
    total = max(1, round(seconds))
    minutes, rest = divmod(total, 60)
    if minutes == 0:
        return f"{rest} 秒"
    if rest == 0:
        return f"{minutes} 分钟"
    return f"{minutes} 分 {rest} 秒"


def format_bytes(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    units = ("KB", "MB", "GB", "TB")
    value = float(size)
    for unit in units:
        value /= 1024
        if value < 1024 or unit == units[-1]:
            return f"{value:.1f} {unit}"
    return f"{value:.1f} TB"


def format_timestamp(value: str | None) -> str:
    """Render a stored UTC ISO timestamp in the server's local timezone."""

    if not value:
        return ""
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        return ""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.astimezone().strftime("%Y-%m-%d %H:%M")
