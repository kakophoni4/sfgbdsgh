"""Выгрузка компактного xlsx в CRM Lavok (вместо Google Sheets).

POST multipart field=file, header X-Lavok-Ingest-Token.
Листы = ДД.ММ.ГГГГ, шапка как у онлайн-таблицы.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import requests
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font
from openpyxl.utils import get_column_letter

from config import (
    CRM_EXPORT_PATH,
    LAVOK_INGEST_TOKEN,
    LAVOK_INGEST_URL,
)
from parser.export_apps_script import SHEET_HEADERS, build_export_body

# CRM ждёт «Отчетность» без ё
CRM_HEADERS = [h.replace("Отчётность", "Отчетность") for h in SHEET_HEADERS]

INN_COL = CRM_HEADERS.index("ИНН") + 1  # 1-based
SCORE_COL = CRM_HEADERS.index("Балл") + 1


def write_crm_xlsx(
    payloads: list[dict[str, Any]],
    path: Path | None = None,
    *,
    skip_duplicates: bool = True,
) -> tuple[Path, dict[str, Any], int]:
    """Пишет xlsx в формате CRM. Возвращает (path, body, skipped)."""
    path = path or CRM_EXPORT_PATH
    body, skipped = build_export_body(payloads, skip_duplicates=skip_duplicates)

    wb = Workbook()
    default = wb.active
    first = True
    for spec in body.get("sheets") or []:
        name = str(spec.get("name") or "лист")[:31]
        headers = list(CRM_HEADERS)
        rows = spec.get("rows") or []
        if first:
            ws = default
            ws.title = name
            first = False
        else:
            ws = wb.create_sheet(name)

        header_font = Font(bold=True)
        for c, title in enumerate(headers, 1):
            cell = ws.cell(1, c, title)
            cell.font = header_font
            cell.alignment = Alignment(wrap_text=True, vertical="top")

        for r, row in enumerate(rows, 2):
            for c, val in enumerate(row, 1):
                # ИНН / Балл — строго текст
                if c in (INN_COL, SCORE_COL) and val not in (None, ""):
                    s = str(val).replace("'", "")
                    if c == INN_COL:
                        s = "".join(ch for ch in s if ch.isdigit())
                    cell = ws.cell(r, c, s)
                    cell.number_format = "@"
                else:
                    cell = ws.cell(r, c, "" if val is None else val)
                cell.alignment = Alignment(wrap_text=True, vertical="top")

        for i in range(1, len(headers) + 1):
            ws.column_dimensions[get_column_letter(i)].width = 14
        ws.column_dimensions["A"].width = 16
        ws.column_dimensions["B"].width = 28
        ws.column_dimensions["C"].width = 14
        ws.freeze_panes = "A2"

    if first:
        default.title = "пусто"
        for c, title in enumerate(CRM_HEADERS, 1):
            default.cell(1, c, title)

    path.parent.mkdir(parents=True, exist_ok=True)
    path = Path(path)
    try:
        wb.save(path)
    except PermissionError:
        from datetime import datetime

        alt = path.with_name(
            f"{path.stem}_{datetime.now().strftime('%Y%m%d_%H%M%S')}{path.suffix}"
        )
        wb.save(alt)
        print(f"CRM xlsx занят ({path.name}) — сохранено как {alt.name}")
        path = alt

    n_rows = sum(len(s.get("rows") or []) for s in (body.get("sheets") or []))
    print(
        f"CRM xlsx: {path} | листов={len(body.get('sheets') or [])} | "
        f"строк={n_rows} | отброшено={skipped}"
    )
    return path, body, skipped


def ingest_crm(
    path: Path,
    *,
    token: str | None = None,
    url: str | None = None,
    retries: int = 4,
) -> dict[str, Any]:
    """POST .xlsx в Lavok ingest (с ретраями при обрыве связи)."""
    import time

    url = (url if url is not None else LAVOK_INGEST_URL).strip()
    token = (token if token is not None else LAVOK_INGEST_TOKEN).strip()
    if not url:
        raise SystemExit("В .env нет LAVOK_INGEST_URL")
    if not token:
        raise SystemExit("В .env нет LAVOK_INGEST_TOKEN")
    path = Path(path)
    if not path.is_file():
        raise SystemExit(f"Нет файла для CRM: {path}")
    if path.suffix.lower() != ".xlsx":
        raise SystemExit(f"CRM принимает только .xlsx, не {path.suffix}")

    size_kb = path.stat().st_size / 1024
    print(
        f"CRM ingest: POST {url} | file={path.name} | size={size_kb:.1f} KB | "
        f"retries={retries}",
        flush=True,
    )
    raw = path.read_bytes()
    headers = {
        "X-Lavok-Ingest-Token": token,
        "User-Agent": "firmy-lavok-parser/1.0",
        "Accept": "application/json",
    }
    last_err: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            resp = requests.post(
                url,
                headers=headers,
                files={
                    "file": (
                        path.name,
                        raw,
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    )
                },
                timeout=(30, 300),
            )
            text = resp.text or ""
            try:
                data = resp.json()
            except Exception:
                data = {"raw": text[:800]}

            if resp.status_code >= 500 or resp.status_code in {408, 429}:
                raise RuntimeError(f"HTTP {resp.status_code}: {data}")

            if resp.status_code >= 400:
                raise SystemExit(f"CRM ingest HTTP {resp.status_code}: {data}")

            print(
                f"CRM ingest: ok | sheets={data.get('sheets')} | "
                f"upserted={data.get('upserted')} | created={data.get('created')} | "
                f"updated={data.get('updated')} | file={path.name} | "
                f"attempt={attempt}",
                flush=True,
            )
            return data if isinstance(data, dict) else {"ok": True, "data": data}
        except SystemExit:
            raise
        except Exception as e:
            last_err = e
            wait = min(30, 2 ** attempt)
            print(
                f"CRM ingest: fail attempt {attempt}/{retries}: {e} — sleep {wait}s",
                flush=True,
            )
            if attempt < retries:
                time.sleep(wait)

    raise SystemExit(f"CRM ingest failed after {retries} attempts: {last_err}")


def export_and_ingest_crm(
    payloads: list[dict[str, Any]],
    *,
    skip_duplicates: bool = True,
    path: Path | None = None,
    upload: bool = True,
) -> Path:
    out, _body, _skipped = write_crm_xlsx(
        payloads, path=path, skip_duplicates=skip_duplicates
    )
    if upload:
        ingest_crm(out)
    return out
