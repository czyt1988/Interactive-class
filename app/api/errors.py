"""Structured API errors.

All API failures use ``{"error": {code, message, details}}``. No endpoint
should leak a bare 500 or FastAPI's default ``{"detail": ...}`` shape.
"""

from __future__ import annotations

from typing import Any


class ApiError(Exception):
    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        **details: Any,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details

    def payload(self) -> dict[str, Any]:
        return {"error": {"code": self.code, "message": self.message, "details": self.details}}
