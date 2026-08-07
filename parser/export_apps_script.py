"""Заливка в Google Sheets через Apps Script (без Google Cloud / service account).

В .env:
  GOOGLE_APPS_SCRIPT_URL=https://script.google.com/macros/s/XXXX/exec
  GOOGLE_APPS_SCRIPT_TOKEN=optional_secret
"""
from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from config import GOOGLE_APPS_SCRIPT_TOKEN, GOOGLE_APPS_SCRIPT_URL
from parser.export_excel import HEADERS, row_from_payload


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

    payloads = sorted(
        payloads,
        key=lambda p: (
            p.get("listing_first_seen") or p.get("msg_date") or "",
            int((p.get("scoring") or {}).get("score") or 0),
        ),
        reverse=True,
    )

    rows: list[list[Any]] = []
    for p in payloads:
        row = []
        for v in row_from_payload(p):
            if v is None:
                row.append("")
            elif isinstance(v, (int, float)):
                row.append(v)
            else:
                s = str(v)
                row.append(s[:49000] if len(s) > 49000 else s)
        rows.append(row)

    payload = {"headers": HEADERS, "rows": rows}
    token = (GOOGLE_APPS_SCRIPT_TOKEN or "").strip()
    post_url = url
    if token:
        sep = "&" if "?" in url else "?"
        post_url = f"{url}{sep}{urlencode({'token': token})}"

    req = Request(
        post_url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    with urlopen(req, timeout=120) as resp:
        raw = resp.read().decode("utf-8", "replace")
    try:
        data = json.loads(raw)
    except Exception:
        # Apps Script иногда отдаёт HTML-редирект — покажем кусок
        raise SystemExit(f"Apps Script ответ не JSON: {raw[:300]}")

    if not data.get("ok"):
        raise SystemExit(f"Apps Script error: {data}")

    print(
        f"Google Sheets (Apps Script): ok | строк={data.get('rows')} | лист={data.get('sheet')}"
    )
    return url
