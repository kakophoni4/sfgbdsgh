"""Заливка в Google Sheets через Apps Script (без Google Cloud / service account).

Листы по дням первого появления в чате — как в Excel.
В .env:
  GOOGLE_APPS_SCRIPT_URL=https://script.google.com/macros/s/XXXX/exec
  GOOGLE_APPS_SCRIPT_TOKEN=optional_secret
"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from config import GOOGLE_APPS_SCRIPT_TOKEN, GOOGLE_APPS_SCRIPT_URL
from parser.export_excel import (
    HEADERS,
    _first_seen_day,
    _sheet_title,
    row_from_payload,
)

_WS = re.compile(r"\s+")


def _sheet_cell(v: Any, *, col_idx: int) -> Any:
    """Плоские ячейки: без переносов строк (иначе Sheets раздувает высоту)."""
    if v is None:
        return ""
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return v
    s = str(v).replace("\r\n", " ").replace("\n", " ").replace("\r", " ")
    s = _WS.sub(" ", s).strip()
    # сырой текст / итог / досье — короче в онлайн-таблице
    if col_idx == len(HEADERS) - 1:  # Сырой текст
        s = s[:400]
    elif col_idx == 24:  # Итог: брать или нет
        s = s[:500]
    elif col_idx == 33:  # Карточка Companium
        s = s[:400]
    else:
        s = s[:2000]
    return s


def _rows_for(payloads: list[dict[str, Any]]) -> list[list[Any]]:
    rows: list[list[Any]] = []
    ordered = sorted(
        payloads,
        key=lambda p: int((p.get("scoring") or {}).get("score") or 0),
        reverse=True,
    )
    for p in ordered:
        raw = row_from_payload(p)
        rows.append([_sheet_cell(v, col_idx=i) for i, v in enumerate(raw)])
    return rows


def export_apps_script(
    payloads: list[dict[str, Any]],
    *,
    skip_duplicates: bool = True,
) -> str:
    url = (GOOGLE_APPS_SCRIPT_URL or "").strip()
    if not url:
        raise SystemExit("В .env нет GOOGLE_APPS_SCRIPT_URL")

    if skip_duplicates:
        payloads = [p for p in payloads if not p.get("is_duplicate")]

    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for p in payloads:
        groups[_first_seen_day(p)].append(p)
    days = sorted(groups.keys(), reverse=True)

    sheets: list[dict[str, Any]] = []
    used_titles: set[str] = set()
    for day in days:
        title = _sheet_title(day)
        base, n = title, 2
        while title in used_titles:
            title = f"{base}_{n}"[:90]
            n += 1
        used_titles.add(title)
        sheets.append(
            {
                "name": title,
                "headers": HEADERS,
                "rows": _rows_for(groups[day]),
            }
        )

    if not sheets:
        sheets = [{"name": "пусто", "headers": HEADERS, "rows": []}]

    body = {"sheets": sheets}
    token = (GOOGLE_APPS_SCRIPT_TOKEN or "").strip()
    post_url = url
    if token:
        sep = "&" if "?" in url else "?"
        post_url = f"{url}{sep}{urlencode({'token': token})}"

    raw_bytes = json.dumps(body, ensure_ascii=False).encode("utf-8")
    # Apps Script ~30–50s лимит; большой JSON может не влезть — тогда чанками
    req = Request(
        post_url,
        data=raw_bytes,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    with urlopen(req, timeout=180) as resp:
        raw = resp.read().decode("utf-8", "replace")
    try:
        data = json.loads(raw)
    except Exception:
        raise SystemExit(f"Apps Script ответ не JSON: {raw[:300]}")

    if not data.get("ok"):
        raise SystemExit(f"Apps Script error: {data}")

    names = data.get("names") or []
    print(
        f"Google Sheets (Apps Script): ok | строк={data.get('rows')} | "
        f"листов={data.get('sheets')} | "
        f"вкладки={', '.join(names[:8])}{'…' if len(names) > 8 else ''}"
    )
    return url
