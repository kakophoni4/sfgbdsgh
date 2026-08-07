"""Сэмпл сообщений из профильных чатов для дизайна парсера."""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path

from dotenv import load_dotenv
from telethon import TelegramClient

ROOT = Path(__file__).resolve().parent
SESSION_PATH = ROOT / "telegram_session"
OUT = ROOT / "chat_samples.json"

OFFICIAL = {
    "api_id": 2040,
    "api_hash": "b18441a1ff607e10a989891a5462e627",
    "device_model": "Desktop",
    "system_version": "Windows 10",
    "app_version": "5.10.5",
    "lang_code": "en",
    "system_lang_code": "en-US",
}

# Кандидаты из первого логина + любые с ключевыми словами
TARGET_IDS = {
    -1001909540858,  # Продажа компаний, готовые ООО
    -1001957737443,  # Регфорум
    -1003962392160,  # НЕ ТВОЙ ЮРИСТ
}

KEYWORDS = re.compile(
    r"продаж|готов(ые|ое)\s+ооо|компани|инн|егрюл|юрлиц|ооо\b|ставк",
    re.I,
)
INN_RE = re.compile(r"\b(\d{10}|\d{12})\b")
PRICE_RE = re.compile(
    r"(?:цена|стоимость|за)\s*[:\-]?\s*(\d[\d\s]{2,})\s*(?:тыс|т\.?\s*р|руб|₽|р\b)?|"
    r"(\d[\d\s]{2,})\s*(?:тыс\.?\s*(?:руб|р)?|000\s*руб|₽)",
    re.I,
)


async def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    load_dotenv(ROOT / ".env")
    client = TelegramClient(
        str(SESSION_PATH),
        OFFICIAL["api_id"],
        OFFICIAL["api_hash"],
        device_model=OFFICIAL["device_model"],
        system_version=OFFICIAL["system_version"],
        app_version=OFFICIAL["app_version"],
        lang_code=OFFICIAL["lang_code"],
        system_lang_code=OFFICIAL["system_lang_code"],
    )
    await client.connect()
    if not await client.is_user_authorized():
        raise SystemExit("Нет сессии. Сначала python telegram_login.py")

    dialogs = []
    async for d in client.iter_dialogs():
        name = d.name or ""
        interesting = d.id in TARGET_IDS or bool(KEYWORDS.search(name))
        if d.is_group or d.is_channel:
            dialogs.append(
                {
                    "id": d.id,
                    "name": name,
                    "is_channel": d.is_channel,
                    "is_group": d.is_group,
                    "unread": d.unread_count,
                    "interesting": interesting,
                }
            )

    print(f"Всего групп/каналов: {len(dialogs)}")
    interesting = [d for d in dialogs if d["interesting"]]
    print(f"Профильные/похожие: {len(interesting)}")
    for d in interesting:
        print(f"  * {d['name']!r} id={d['id']} unread={d['unread']}")

    samples = {}
    stats = {}

    for d in interesting:
        entity = await client.get_entity(d["id"])
        msgs = []
        inn_hits = 0
        price_hits = 0
        with_text = 0
        senders = Counter()

        async for m in client.iter_messages(entity, limit=80):
            text = (m.message or "").strip()
            if not text:
                continue
            with_text += 1
            inns = INN_RE.findall(text)
            prices = PRICE_RE.findall(text)
            if inns:
                inn_hits += 1
            if prices:
                price_hits += 1
            sender = None
            if m.sender:
                sender = getattr(m.sender, "username", None) or getattr(
                    m.sender, "first_name", None
                )
            if sender:
                senders[str(sender)] += 1

            # ссылка на сообщение
            if d["is_channel"] or str(d["id"]).startswith("-100"):
                # channel/supergroup
                internal = abs(d["id"]) - 1000000000000 if abs(d["id"]) > 10**12 else abs(d["id"])
                # Telethon: for -100xxxxxxxxxx, link is t.me/c/<xxxxxxxx>/<msg_id>
                raw = str(abs(d["id"]))
                if raw.startswith("100"):
                    link_id = raw[3:]
                else:
                    link_id = raw
                link = f"https://t.me/c/{link_id}/{m.id}"
            else:
                link = f"msg:{d['id']}/{m.id}"

            if len(msgs) < 25 and (inns or KEYWORDS.search(text) or "ИНН" in text.upper()):
                msgs.append(
                    {
                        "id": m.id,
                        "date": m.date.isoformat() if m.date else None,
                        "sender": sender,
                        "link": link,
                        "inns": inns,
                        "has_price_pattern": bool(prices),
                        "text": text[:1500],
                    }
                )

        samples[str(d["id"])] = {
            "name": d["name"],
            "messages": msgs,
        }
        stats[d["name"]] = {
            "id": d["id"],
            "scanned_with_text": with_text,
            "with_inn": inn_hits,
            "with_price_pattern": price_hits,
            "top_senders": senders.most_common(8),
            "sample_count": len(msgs),
        }
        print(
            f"\n=== {d['name']} ===\n"
            f"text={with_text}, INN={inn_hits}, price~={price_hits}, samples={len(msgs)}"
        )
        for s in msgs[:3]:
            print("---")
            print(s["text"][:500])
            print("INNs:", s["inns"], "link:", s["link"])

    OUT.write_text(
        json.dumps({"stats": stats, "samples": samples}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\nСохранено: {OUT}")
    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
