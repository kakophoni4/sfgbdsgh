from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from telethon import TelegramClient, events
from telethon.tl.custom.message import Message

from config import CHAT_IDS, HISTORY_LIMIT

from .db import ListingDB
from .extract import parse_message
from .score import score_listing


def _sender_name(msg: Message) -> str:
    sender = msg.sender
    if not sender:
        return ""
    return getattr(sender, "username", None) or getattr(sender, "first_name", None) or ""


def _msg_date(msg: Message) -> str:
    if not msg.date:
        return datetime.now(timezone.utc).isoformat()
    return msg.date.isoformat()


async def process_message(msg: Message, db: ListingDB, chat_id: int) -> int:
    text = (msg.message or "").strip()
    if not text:
        return 0
    listings = parse_message(
        text,
        chat_id=chat_id,
        message_id=msg.id,
        sender=_sender_name(msg),
        msg_date=_msg_date(msg),
    )
    for item in listings:
        scored = score_listing(item)
        db.upsert(item, scored)
    return len(listings)


async def scrape_history(
    client: TelegramClient,
    db: ListingDB,
    chat_ids: list[int] | None = None,
    limit: int = HISTORY_LIMIT,
) -> dict:
    chat_ids = chat_ids or CHAT_IDS
    total_msgs = 0
    total_listings = 0

    for chat_id in chat_ids:
        entity = await client.get_entity(chat_id)
        title = getattr(entity, "title", None) or str(chat_id)
        print(f"Сканирую: {title} ({chat_id}), limit={limit}")
        async for msg in client.iter_messages(entity, limit=limit):
            total_msgs += 1
            n = await process_message(msg, db, chat_id)
            total_listings += n
            if total_msgs % 50 == 0:
                print(f"  ... сообщений {total_msgs}, лотов накоплено +{total_listings}")

    stats = db.stats()
    print(
        f"Готово: msgs={total_msgs}, новых/обновлённых лотов за проход≈{total_listings}, "
        f"в базе={stats['total']} (с ИНН={stats['with_inn']}, вердикт ДА={stats['verdict_yes']})"
    )
    return {"messages": total_msgs, "listings_seen": total_listings, **stats}


async def listen_live(client: TelegramClient, db: ListingDB, chat_ids: list[int] | None = None) -> None:
    chat_ids = chat_ids or CHAT_IDS
    print(f"Live-слушаю чаты: {chat_ids}. Ctrl+C для выхода.")

    @client.on(events.NewMessage(chats=chat_ids))
    async def handler(event: events.NewMessage.Event) -> None:
        n = await process_message(event.message, db, event.chat_id)
        if n:
            print(f"+{n} лот(ов) из msg {event.message.id}")

    await client.run_until_disconnected()
