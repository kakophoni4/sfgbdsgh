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

# Сколько сообщений тянуть при backfill
HISTORY_LIMIT = int(os.getenv("HISTORY_LIMIT", "400"))

# Паузы обогащения: итого ~ ENRICH_PAUSE .. ENRICH_PAUSE+ENRICH_JITTER сек
# При капче ЕГРЮЛ/БФО подними, например ENRICH_PAUSE=10 ENRICH_JITTER=5
ENRICH_PAUSE = float(os.getenv("ENRICH_PAUSE", "2.5"))
ENRICH_JITTER = float(os.getenv("ENRICH_JITTER", "1.0"))
# лимит лотов за один прогон enrich
ENRICH_LIMIT = int(os.getenv("ENRICH_LIMIT", "40"))

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
