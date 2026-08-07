"""Живой статус прогона: data/STATUS.txt + data/status.json

Смотреть на сервере:
  type C:\\firmy\\data\\STATUS.txt
  powershell -File deploy\\show_status.ps1
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from config import DATA_DIR
except Exception:
    DATA_DIR = Path(__file__).resolve().parents[1] / "data"

STATUS_JSON = Path(DATA_DIR) / "status.json"
STATUS_TXT = Path(DATA_DIR) / "STATUS.txt"


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S")


def write_status(
    *,
    stage: str,
    detail: str = "",
    source: str = "",
    current: int = 0,
    total: int = 0,
    key: str = "",
    extra: dict[str, Any] | None = None,
) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "updated_at": _now(),
        "ts": time.time(),
        "stage": stage,
        "detail": detail,
        "source": source,
        "current": current,
        "total": total,
        "key": key,
        "pct": round(100.0 * current / total, 1) if total else 0,
    }
    if extra:
        payload.update(extra)
    STATUS_JSON.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    bar_total = 20
    filled = int(bar_total * current / total) if total else 0
    bar = "█" * filled + "░" * (bar_total - filled)
    lines = [
        f"Обновлено: {payload['updated_at']}",
        f"Этап:      {stage}",
        f"Детали:    {detail}",
    ]
    if source:
        lines.append(f"Источник:  {source}")
    if total:
        lines.append(f"Прогресс:  [{bar}] {current}/{total} ({payload['pct']}%)")
    if key:
        lines.append(f"Сейчас:    {key}")
    lines.append("")
    lines.append("Логи: data\\logs\\")
    STATUS_TXT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def mark_skip(reason: str = "already running") -> None:
    write_status(stage="SKIP", detail=reason)


def mark_done(detail: str = "ok") -> None:
    write_status(stage="DONE", detail=detail)
