from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
ENV_PATH = ROOT / ".env"
load_dotenv(ENV_PATH)

DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)

SESSION_PATH = ROOT / "telegram_session"
DB_PATH = DATA_DIR / "listings.db"
EXPORT_PATH = DATA_DIR / "checklist_export.xlsx"

# Главный чат продаж
CHAT_IDS = [
    -1001909540858,  # Продажа компаний, готовые ООО
]

# Сколько сообщений тянуть при backfill (потолок; с --since-days режет по дате)
HISTORY_LIMIT = int(os.getenv("HISTORY_LIMIT", "400"))
# По умолчанию для fresh-прогонов можно задать в .env: SINCE_DAYS=30
SINCE_DAYS = int(os.getenv("SINCE_DAYS", "0")) or None

# Google Sheets (опционально) — service account (нужен Google Cloud)
GOOGLE_SHEETS_ID = os.getenv("GOOGLE_SHEETS_ID", "").strip()
GOOGLE_SERVICE_ACCOUNT_JSON = os.getenv(
    "GOOGLE_SERVICE_ACCOUNT_JSON", str(ROOT / "secrets" / "gsheets.json")
).strip()
# Google Sheets через Apps Script (без Cloud / карты) — предпочтительно
GOOGLE_APPS_SCRIPT_URL = os.getenv("GOOGLE_APPS_SCRIPT_URL", "").strip()
GOOGLE_APPS_SCRIPT_TOKEN = os.getenv("GOOGLE_APPS_SCRIPT_TOKEN", "").strip()

# Паузы обогащения: итого ~ ENRICH_PAUSE .. ENRICH_PAUSE+ENRICH_JITTER сек
# При капче ЕГРЮЛ/БФО подними, например ENRICH_PAUSE=10 ENRICH_JITTER=5
ENRICH_PAUSE = float(os.getenv("ENRICH_PAUSE", "2.5"))
ENRICH_JITTER = float(os.getenv("ENRICH_JITTER", "1.0"))
# лимит лотов за один прогон enrich
ENRICH_LIMIT = int(os.getenv("ENRICH_LIMIT", "40"))
# HTTP(S) прокси ТОЛЬКО для Companium/Checko (БФО/ЕГРЮЛ/Федресурс — напрямую).
# Список (host:port, whitelist IP) — предпочтительно:
ENRICH_PROXY_LIST_URL = os.getenv("ENRICH_PROXY_LIST_URL", "").strip()
ENRICH_PROXY_LIST_TTL = float(os.getenv("ENRICH_PROXY_LIST_TTL", "900"))  # сек кэша
ENRICH_PROXY_TRIES = int(os.getenv("ENRICH_PROXY_TRIES", "8"))  # попыток на запрос
# Одиночный прокси (если списка нет): http://user:pass@host:443
ENRICH_PROXY = os.getenv("ENRICH_PROXY", "").strip()

# Официальный Desktop API (как в telegram_login.py)
OFFICIAL_API = {
    "api_id": 2040,
    "api_hash": "b18441a1ff607e10a989891a5462e627",
    "device_model": "Desktop",
    "system_version": "Windows 10",
    "app_version": "5.10.5",
    "lang_code": "en",
    "system_lang_code": "en-US",
}
