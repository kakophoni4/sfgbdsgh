from __future__ import annotations

import hashlib
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from config import (
    CRM_EXPORT_PATH,
    LAVOK_EXPORT_HOST,
    LAVOK_EXPORT_PORT,
    LAVOK_INGEST_TOKEN,
)

PATHS = {"/lavok/export.xlsx", "/lavok/export.xlsx/"}
_WRITE_CHUNK = 512
_RANGE_RE = re.compile(r"bytes=(\d+)-(\d*)$", re.I)


def _token_ok(handler: BaseHTTPRequestHandler) -> bool:
    expected = (LAVOK_INGEST_TOKEN or "").strip()
    if not expected:
        handler.send_error(503, "LAVOK_INGEST_TOKEN is not set")
        return False
    got = (handler.headers.get("X-Lavok-Ingest-Token") or "").strip()
    if got != expected:
        handler.send_error(403, "Invalid ingest token")
        return False
    return True


def _parse_range(header: str, size: int) -> tuple[int, int] | None:
    raw = (header or "").strip()
    match = _RANGE_RE.match(raw)
    if not match:
        return None
    start = int(match.group(1))
    end = int(match.group(2)) if match.group(2) else size - 1
    end = min(end, size - 1)
    if start > end or start >= size:
        return None
    return start, end


def _write(handler: BaseHTTPRequestHandler, payload: bytes) -> None:
    view = memoryview(payload)
    offset = 0
    while offset < len(view):
        handler.wfile.write(view[offset : offset + _WRITE_CHUNK])
        handler.wfile.flush()
        offset += _WRITE_CHUNK


class ExportHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args: object) -> None:
        print(f"lavok-export: {self.address_string()} {fmt % args}", flush=True)

    def do_GET(self) -> None:  # noqa: N802
        path = (self.path or "/").split("?", 1)[0]
        if path == "/healthz":
            body = b"ok"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(body)
            return
        if path not in PATHS:
            self.send_error(404, "Not found")
            return
        if not _token_ok(self):
            return
        path_file = Path(CRM_EXPORT_PATH)
        if not path_file.is_file():
            self.send_error(404, "lavok_parser.xlsx not ready yet")
            return
        data = path_file.read_bytes()
        etag = hashlib.sha256(data).hexdigest()
        inm = (self.headers.get("If-None-Match") or "").strip().strip('"')
        if inm and inm == etag:
            self.send_response(304)
            self.send_header("ETag", f'"{etag}"')
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Connection", "close")
            self.end_headers()
            return

        parsed = _parse_range(self.headers.get("Range") or "", len(data))
        range_hdr = (self.headers.get("Range") or "").strip()
        if range_hdr and parsed is None:
            self.send_response(416)
            self.send_header("Content-Range", f"bytes */{len(data)}")
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Length", "0")
            self.send_header("Connection", "close")
            self.end_headers()
            return

        if parsed is None:
            start, end = 0, len(data) - 1
            status = 200
        else:
            start, end = parsed
            status = 206
        blob = data[start : end + 1]
        self.send_response(status)
        self.send_header(
            "Content-Type",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        self.send_header("Content-Disposition", 'attachment; filename="lavok_parser.xlsx"')
        self.send_header("Accept-Ranges", "bytes")
        if status == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{len(data)}")
        self.send_header("Content-Length", str(len(blob)))
        self.send_header("ETag", f'"{etag}"')
        self.send_header("Connection", "close")
        self.end_headers()
        _write(self, blob)


def main() -> None:
    if not (LAVOK_INGEST_TOKEN or "").strip():
        raise SystemExit("В .env нет LAVOK_INGEST_TOKEN")
    server = ThreadingHTTPServer((LAVOK_EXPORT_HOST, LAVOK_EXPORT_PORT), ExportHandler)
    print(
        f"Lavok export listening on http://{LAVOK_EXPORT_HOST}:{LAVOK_EXPORT_PORT}/lavok/export.xlsx",
        flush=True,
    )
    server.serve_forever()


if __name__ == "__main__":
    main()
