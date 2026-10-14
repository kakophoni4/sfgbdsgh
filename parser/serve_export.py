from __future__ import annotations

import hashlib
import hmac
import json
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

from config import (
    CRM_EXPORT_PATH,
    LAVOK_EXPORT_HOST,
    LAVOK_EXPORT_PORT,
    LAVOK_INGEST_TOKEN,
    DATA_DIR,
    ROOT,
)
from parser.company_checks import JobStore, JobWorker, MAX_UPLOAD

PATHS = {"/lavok/export.xlsx", "/lavok/export.xlsx/"}
_WRITE_CHUNK = 512
_RANGE_RE = re.compile(r"bytes=(\d+)-(\d*)$", re.I)


def _token_ok(handler: BaseHTTPRequestHandler) -> bool:
    expected = (LAVOK_INGEST_TOKEN or "").strip()
    if not expected:
        handler.send_error(503, "LAVOK_INGEST_TOKEN is not set")
        return False
    got = (handler.headers.get("X-Lavok-Ingest-Token") or "").strip()
    if not hmac.compare_digest(got, expected):
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

    def json_response(self, status: int, body: dict | list) -> None:
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(payload)

    def check_routes(self, method: str) -> bool:
        path = urlsplit(self.path).path.rstrip("/")
        if not path.startswith("/lavok/checks"):
            return False
        if not _token_ok(self):
            return True
        owner = (self.headers.get("X-Lavok-Owner") or "").strip()
        if not re.fullmatch(r"[a-zA-Z0-9:_-]{1,100}", owner):
            self.json_response(400,{"error":"Missing job owner"})
            return True
        store = self.server.job_store
        parts = path.split("/")[3:]
        try:
            if not parts and method == "GET":
                self.json_response(200,{"items":store.list(owner)})
            elif not parts and method == "POST":
                try:
                    length = int(self.headers.get("Content-Length") or "0")
                except ValueError:
                    length = 0
                if not 0 < length <= MAX_UPLOAD:
                    self.json_response(413,{"error":"Upload must be 1..20 MB"})
                    return True
                self.connection.settimeout(60)
                content = self.rfile.read(length)
                if len(content) != length:
                    raise ValueError("Incomplete upload")
                filename = unquote(self.headers.get("X-Lavok-Filename") or "companies.xlsx")
                if not filename.lower().endswith(".xlsx"):
                    raise ValueError("Нужен файл .xlsx")
                self.json_response(202,store.create(content,filename,owner))
            elif len(parts) == 1 and method == "GET":
                self.json_response(200,store.get(parts[0],owner))
            elif len(parts) == 2 and parts[1] == "cancel" and method == "POST":
                self.json_response(200,store.cancel(parts[0],owner))
            elif len(parts) == 2 and parts[1] == "resume" and method == "POST":
                self.json_response(200,store.resume(parts[0],owner,retry_errors=True))
            elif len(parts) == 2 and parts[1] == "result.xlsx" and method == "GET":
                info = store.get(parts[0],owner)
                if not info["result_ready"]:
                    self.json_response(409,{"error":"Результат ещё не готов"})
                else:
                    self.send_file(store.result_path(parts[0]),"company_checks.xlsx")
            else:
                self.json_response(404,{"error":"Not found"})
        except KeyError:
            self.json_response(404,{"error":"Job not found"})
        except ValueError as exc:
            self.json_response(422,{"error":str(exc)})
        return True

    def do_POST(self) -> None:  # noqa: N802
        if not self.check_routes("POST"):
            self.send_error(404,"Not found")

    def log_message(self, fmt: str, *args: object) -> None:
        print(f"lavok-export: {self.address_string()} {fmt % args}", flush=True)

    def do_GET(self) -> None:  # noqa: N802
        if self.check_routes("GET"):
            return
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
        self.send_file(path_file,"lavok_parser.xlsx")

    def send_file(self, path_file: Path, filename: str) -> None:
        with path_file.open("rb") as file:
            import os
            stat = os.fstat(file.fileno())
            size = stat.st_size
            etag = hashlib.sha256(f"{stat.st_ino}:{size}:{stat.st_mtime_ns}".encode()).hexdigest()
            parsed = _parse_range(self.headers.get("Range") or "", size)
            if parsed:
                file.seek(parsed[0])
                blob = file.read(parsed[1]-parsed[0]+1)
            elif not self.headers.get("Range"):
                blob = file.read()
            else:
                blob = b""
        inm = (self.headers.get("If-None-Match") or "").strip().strip('"')
        if inm and inm == etag:
            self.send_response(304)
            self.send_header("ETag", f'"{etag}"')
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Connection", "close")
            self.end_headers()
            return

        range_hdr = (self.headers.get("Range") or "").strip()
        if range_hdr and parsed is None:
            self.send_response(416)
            self.send_header("Content-Range", f"bytes */{size}")
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Length", "0")
            self.send_header("Connection", "close")
            self.end_headers()
            return

        if parsed is None:
            start, end = 0, size - 1
            status = 200
        else:
            start, end = parsed
            status = 206
        self.send_response(status)
        self.send_header(
            "Content-Type",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.send_header("Accept-Ranges", "bytes")
        if status == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.send_header("Content-Length", str(len(blob)))
        self.send_header("ETag", f'"{etag}"')
        self.send_header("Connection", "close")
        self.end_headers()
        _write(self, blob)


def main() -> None:
    if not (LAVOK_INGEST_TOKEN or "").strip():
        raise SystemExit("В .env нет LAVOK_INGEST_TOKEN")
    server = ThreadingHTTPServer((LAVOK_EXPORT_HOST, LAVOK_EXPORT_PORT), ExportHandler)
    server.job_store = JobStore(DATA_DIR / "company_checks")
    worker = JobWorker(server.job_store,ROOT)
    worker.start()
    print(
        f"Lavok export listening on http://{LAVOK_EXPORT_HOST}:{LAVOK_EXPORT_PORT}/lavok/export.xlsx",
        flush=True,
    )
    try:
        server.serve_forever()
    finally:
        worker.stopping.set()
        if worker.thread:
            worker.thread.join(timeout=20)
        server.server_close()


if __name__ == "__main__":
    main()
