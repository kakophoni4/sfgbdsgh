from __future__ import annotations

import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from config import (
    CRM_EXPORT_PATH,
    LAVOK_EXPORT_HOST,
    LAVOK_EXPORT_PORT,
    LAVOK_INGEST_TOKEN,
)

PATHS = {"/lavok/export.xlsx", "/lavok/export.xlsx/"}


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


class ExportHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args: object) -> None:
        print(f"lavok-export: {self.address_string()} {fmt % args}", flush=True)

    def do_GET(self) -> None:  # noqa: N802
        path = (self.path or "/").split("?", 1)[0]
        if path == "/healthz":
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"ok")
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
            self.end_headers()
            return
        self.send_response(200)
        self.send_header(
            "Content-Type",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        self.send_header("Content-Disposition", 'attachment; filename="lavok_parser.xlsx"')
        self.send_header("Content-Length", str(len(data)))
        self.send_header("ETag", f'"{etag}"')
        self.end_headers()
        self.wfile.write(data)


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
