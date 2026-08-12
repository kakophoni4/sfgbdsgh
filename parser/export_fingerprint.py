"""Отпечаток выгрузки: не дёргать Sheets/Excel, если данные те же."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from config import DATA_DIR

FP_PATH = DATA_DIR / "export_fingerprint.txt"


def fingerprint(obj: Any) -> str:
    raw = json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def load_fingerprint(path: Path | None = None) -> str:
    p = path or FP_PATH
    if not p.is_file():
        return ""
    return p.read_text(encoding="utf-8").strip()


def save_fingerprint(fp: str, path: Path | None = None) -> None:
    p = path or FP_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(fp.strip() + "\n", encoding="utf-8")
