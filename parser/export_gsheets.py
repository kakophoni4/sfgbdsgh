"""Выгрузка уникальных лотов в Google Sheets (service account).

Нужно в .env:
  GOOGLE_SHEETS_ID=....   # id из URL таблицы
  GOOGLE_SERVICE_ACCOUNT_JSON=C:\\firmy\\secrets\\gsheets.json

Таблица должна быть расшарена на email сервисного аккаунта (Editor).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from config import GOOGLE_SERVICE_ACCOUNT_JSON, GOOGLE_SHEETS_ID
from parser.export_excel import HEADERS, row_from_payload


def _client():
    try:
        import gspread
        from google.oauth2.service_account import Credentials
    except ImportError as e:
        raise SystemExit(
            "Нужны пакеты: pip install gspread google-auth\n" + str(e)
        ) from e

    path = Path(GOOGLE_SERVICE_ACCOUNT_JSON or "")
    if not GOOGLE_SHEETS_ID:
        raise SystemExit("В .env нет GOOGLE_SHEETS_ID")
    if not path.is_file():
        raise SystemExit(f"Нет файла ключа: {path}")

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_file(str(path), scopes=scopes)
    return gspread.authorize(creds)


def export_gsheets(
    payloads: list[dict[str, Any]],
    *,
    worksheet_title: str = "Лоты",
    skip_duplicates: bool = True,
) -> str:
    if skip_duplicates:
        payloads = [p for p in payloads if not p.get("is_duplicate")]

    # свежие сверху
    payloads = sorted(
        payloads,
        key=lambda p: (
            p.get("listing_first_seen") or p.get("msg_date") or "",
            int((p.get("scoring") or {}).get("score") or 0),
        ),
        reverse=True,
    )

    rows = [HEADERS]
    for p in payloads:
        rows.append([_cell(v) for v in row_from_payload(p)])

    gc = _client()
    sh = gc.open_by_key(GOOGLE_SHEETS_ID)
    try:
        ws = sh.worksheet(worksheet_title)
    except Exception:
        ws = sh.add_worksheet(
            title=worksheet_title,
            rows=max(len(rows) + 50, 100),
            cols=max(len(HEADERS) + 5, 40),
        )

    ws.clear()
    # gspread batch update
    ws.update("A1", rows, value_input_option="USER_ENTERED")
    url = f"https://docs.google.com/spreadsheets/d/{GOOGLE_SHEETS_ID}"
    print(f"Google Sheets: {url} | лист «{worksheet_title}» | строк={len(payloads)}")
    return url


def _cell(v: Any) -> str | int | float:
    if v is None:
        return ""
    if isinstance(v, (int, float)):
        return v
    s = str(v)
    # лимит ячейки Sheets ~50k
    return s[:49000] if len(s) > 49000 else s


def credentials_email() -> str:
    path = Path(GOOGLE_SERVICE_ACCOUNT_JSON or "")
    if not path.is_file():
        return ""
    data = json.loads(path.read_text(encoding="utf-8"))
    return str(data.get("client_email") or "")
