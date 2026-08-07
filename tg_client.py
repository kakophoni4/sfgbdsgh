from __future__ import annotations

import os

from dotenv import load_dotenv
from telethon import TelegramClient

from config import ENV_PATH, OFFICIAL_API, SESSION_PATH


def make_client() -> TelegramClient:
    load_dotenv(ENV_PATH)
    mode = (os.getenv("USE_OFFICIAL_API") or "desktop").strip().lower()
    custom_id = os.getenv("TELEGRAM_API_ID", "").strip()
    custom_hash = os.getenv("TELEGRAM_API_HASH", "").strip()

    if mode in ("0", "false", "no", "off", "custom") and custom_id and custom_hash:
        return TelegramClient(str(SESSION_PATH), int(custom_id), custom_hash)

    cfg = OFFICIAL_API
    return TelegramClient(
        str(SESSION_PATH),
        cfg["api_id"],
        cfg["api_hash"],
        device_model=cfg["device_model"],
        system_version=cfg["system_version"],
        app_version=cfg["app_version"],
        lang_code=cfg["lang_code"],
        system_lang_code=cfg["system_lang_code"],
    )
