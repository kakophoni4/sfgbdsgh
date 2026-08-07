"""
Вход в Telegram через Telethon.

По умолчанию USE_OFFICIAL_API=desktop — api_id/api_hash официального
Telegram Desktop (не my.telegram.org, не Bot API).
Сессия: telegram_session.session
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from telethon import TelegramClient
from telethon.errors import SessionPasswordNeededError

ROOT = Path(__file__).resolve().parent
SESSION_PATH = ROOT / "telegram_session"
ENV_PATH = ROOT / ".env"

# Официальные credentials клиентов Telegram (публичные, из исходников приложений)
OFFICIAL_APIS = {
    "desktop": {
        "api_id": 2040,
        "api_hash": "b18441a1ff607e10a989891a5462e627",
        "device_model": "Desktop",
        "system_version": "Windows 10",
        "app_version": "5.10.5",
        "lang_code": "en",
        "system_lang_code": "en-US",
    },
    "android": {
        "api_id": 6,
        "api_hash": "eb06d4abfb49dc3eeb1aeb98ae0f581e",
        "device_model": "Samsung SM-G998B",
        "system_version": "SDK 31",
        "app_version": "11.2.0",
        "lang_code": "en",
        "system_lang_code": "en-US",
    },
}


def _prompt(text: str, default: str = "") -> str:
    hint = f" [{default}]" if default else ""
    value = input(f"{text}{hint}: ").strip()
    return value or default


def resolve_api() -> tuple[int, str, dict]:
    """Возвращает api_id, api_hash и kwargs для TelegramClient."""
    load_dotenv(ENV_PATH)

    mode = (os.getenv("USE_OFFICIAL_API") or "desktop").strip().lower()
    custom_id = os.getenv("TELEGRAM_API_ID", "").strip()
    custom_hash = os.getenv("TELEGRAM_API_HASH", "").strip()

    # Явно свои ключи — только если оба заданы и official выключен
    if mode in ("0", "false", "no", "off", "custom") and custom_id and custom_hash:
        return int(custom_id), custom_hash, {}

    if mode not in OFFICIAL_APIS:
        print(f"Неизвестный USE_OFFICIAL_API={mode!r}, беру desktop.", file=sys.stderr)
        mode = "desktop"

    cfg = OFFICIAL_APIS[mode]
    print(f"API: официальный клиент ({mode}), api_id={cfg['api_id']}")
    client_kwargs = {
        "device_model": cfg["device_model"],
        "system_version": cfg["system_version"],
        "app_version": cfg["app_version"],
        "lang_code": cfg["lang_code"],
        "system_lang_code": cfg["system_lang_code"],
    }
    return cfg["api_id"], cfg["api_hash"], client_kwargs


def ensure_env(phone: str) -> None:
    if ENV_PATH.exists():
        text = ENV_PATH.read_text(encoding="utf-8")
        if "USE_OFFICIAL_API" in text and "TELEGRAM_PHONE" in text:
            # обновим телефон, если пустой
            if "TELEGRAM_PHONE=" in text and not os.getenv("TELEGRAM_PHONE"):
                pass
            return

    ENV_PATH.write_text(
        "USE_OFFICIAL_API=desktop\n"
        f"TELEGRAM_PHONE={phone}\n"
        "# Свои ключи нужны только при USE_OFFICIAL_API=off\n"
        "# TELEGRAM_API_ID=\n"
        "# TELEGRAM_API_HASH=\n",
        encoding="utf-8",
    )
    print(f"Сохранено в {ENV_PATH.name}")


async def login() -> None:
    load_dotenv(ENV_PATH)
    api_id, api_hash, client_kwargs = resolve_api()

    phone = os.getenv("TELEGRAM_PHONE", "").strip()
    if not phone:
        phone = _prompt("Номер телефона (+7...)")
    if not phone.startswith("+"):
        print("Номер лучше в формате +79001234567", file=sys.stderr)

    ensure_env(phone)

    client = TelegramClient(
        str(SESSION_PATH),
        api_id,
        api_hash,
        **client_kwargs,
    )

    await client.connect()

    if await client.is_user_authorized():
        me = await client.get_me()
        print(
            f"Уже авторизован: {me.first_name or ''} "
            f"(@{me.username or '—'}), id={me.id}"
        )
        print(f"Сессия: {SESSION_PATH}.session")
    else:
        print(f"Отправляю код на {phone}...")
        await client.send_code_request(phone)
        code = _prompt("Код из Telegram / SMS")

        try:
            await client.sign_in(phone=phone, code=code)
        except SessionPasswordNeededError:
            password = _prompt("Пароль 2FA (облачный пароль)")
            await client.sign_in(password=password)

        me = await client.get_me()
        print(
            f"Вход выполнен: {me.first_name or ''} "
            f"(@{me.username or '—'}), id={me.id}"
        )
        print(f"Сессия сохранена: {SESSION_PATH}.session")

    print("\nПоследние диалоги (до 30):")
    count = 0
    async for dialog in client.iter_dialogs(limit=30):
        kind = "чат/канал" if dialog.is_group or dialog.is_channel else "личка"
        unread = f", непрочит.: {dialog.unread_count}" if dialog.unread_count else ""
        print(f"  [{kind}] {dialog.name!r} (id={dialog.id}{unread})")
        count += 1
    print(f"Показано: {count}")

    await client.disconnect()


if __name__ == "__main__":
    try:
        asyncio.run(login())
    except KeyboardInterrupt:
        print("\nОтменено.")
        sys.exit(130)
