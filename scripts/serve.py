"""Serve a built course bundle over HTTP for standalone verification.

``python -m http.server`` inherits MIME types from the Windows registry, where
``.js`` is sometimes mapped to ``text/plain``; browsers then refuse to run the
deck's ES module. This server pins the few types a course bundle needs so the
"independent static server" check is honest.

Usage:
    python scripts/serve.py dist/courses/<slug> --port 8081
"""

from __future__ import annotations

import argparse
import functools
import http.server
import pathlib
import socketserver
import sys

MIME_OVERRIDES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".woff2": "font/woff2",
    ".woff": "font/woff",
    ".webp": "image/webp",
    ".avif": "image/avif",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".mp4": "video/mp4",
    ".mp3": "audio/mpeg",
    ".ogg": "audio/ogg",
    ".opus": "audio/opus",
    ".m4a": "audio/mp4",
    ".txt": "text/plain; charset=utf-8",
    ".xml": "application/xml",
}


class CourseRequestHandler(http.server.SimpleHTTPRequestHandler):
    extensions_map = {**http.server.SimpleHTTPRequestHandler.extensions_map, **MIME_OVERRIDES}

    def end_headers(self) -> None:  # noqa: D401 - http.server hook
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        super().end_headers()

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002 - http.server signature
        sys.stderr.write(f"{self.address_string()} - {format % args}\n")


class ReusableTCPServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def serve(directory: pathlib.Path, port: int, bind: str = "127.0.0.1") -> None:
    if not directory.is_dir():
        raise SystemExit(f"目录不存在：{directory}")
    handler = functools.partial(CourseRequestHandler, directory=str(directory))
    with ReusableTCPServer((bind, port), handler) as httpd:
        print(f"serving {directory} at http://{bind}:{port}/", file=sys.stderr)
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("stopped", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="用正确的 MIME 类型静态服务一个课程包")
    parser.add_argument("directory", nargs="?", default="dist/courses")
    parser.add_argument("--port", type=int, default=8081)
    parser.add_argument("--bind", default="127.0.0.1")
    args = parser.parse_args(argv)
    serve(pathlib.Path(args.directory).resolve(), args.port, args.bind)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
