"""
Запуск парсера продажи компаний.

Примеры:
  python run_parser.py
  python run_parser.py --enrich-buh --enrich-limit 20
  python run_parser.py --enrich-only
  python run_parser.py --export-only
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import DB_PATH, ENRICH_LIMIT, ENRICH_PAUSE, EXPORT_PATH, HISTORY_LIMIT
from parser.db import ListingDB
from parser.dedup import mark_duplicates, unique_only
from parser.export_excel import export_xlsx
from parser.scrape import listen_live, scrape_history
from tg_client import make_client


def selftest() -> None:
    from parser.extract import parse_message
    from parser.score import score_listing

    samples = [
        (
            "✅ ООО «Новый Алгоритм»\nИНН 7733475417\nРегистрация 19.09.2025 г.\n\nОСНО\n🟢 Зеленая по ЗСК\n💵 Цена 90 т.р.\n\n"
            "✅ ООО «СК Технолоджи»\nИНН 9728133965\nРегистрация 28.05.2024 г.\nОСНО\n💵 Цена 70 т.р.",
            2,
        ),
        (
            'ООО "МЕГАПОЛИС-М"\nМСК (ИФНС 4)\nУСН 15%\n19.08.2020\nВыручка\n2024 - 207.5 млн\n2025 - 301.7 млн\n'
            "✅ В черных списках ЦБ, ЗСК, 115 и 764-П не найдено!\nСтоимость 1.8 млн\n✍ Для связи @LPoint_msk",
            1,
        ),
        (
            "Каталог готовых ООО\nБолее 300 актуальных предложений.\nhttps://consalt-b.ru/ooo",
            0,
        ),
    ]
    ok = True
    for text, expect in samples:
        got = parse_message(text, chat_id=-1001909540858, message_id=1, sender="test")
        print(f"expect={expect} got={len(got)} names={[g.name for g in got]}")
        if len(got) != expect:
            ok = False
        for g in got:
            s = score_listing(g)
            print(
                f"  {g.name} inn={g.inn} price={g.price_rub} → {s['verdict']} {s['score']}"
            )
    if not ok:
        raise SystemExit("selftest failed")
    print("selftest OK")


def export_from_db(db: ListingDB) -> Path:
    payloads = mark_duplicates(db.all_payloads())
    for p in payloads:
        db.save_payload(p)
    uniq = unique_only(payloads)
    path = export_xlsx(uniq, EXPORT_PATH, skip_duplicates=False)
    print(
        f"Excel: {path} | всего={len(payloads)} | уникальных={len(uniq)} | "
        f"stats={db.stats()}"
    )
    return path


def resolve_sources(args: argparse.Namespace) -> list[str]:
    if args.enrich_buh and not args.enrich_egrul and not args.enrich and not args.enrich_only:
        return ["buh"]
    if args.enrich_egrul and not args.enrich_buh and not args.enrich and not args.enrich_only:
        return ["egrul"]
    if args.enrich_buh and args.enrich_egrul:
        return ["egrul", "buh"]
    if args.enrich or args.enrich_only:
        sources = ["egrul", "buh"]
        if args.enrich_buh and not args.enrich_egrul:
            sources = ["buh"]
        if args.enrich_egrul and not args.enrich_buh:
            sources = ["egrul"]
        return sources
    return []


async def async_main(args: argparse.Namespace) -> None:
    db = ListingDB(DB_PATH)
    client = None
    sources = resolve_sources(args)
    do_enrich = bool(sources)
    do_scrape = not args.export_only and not args.enrich_only and not (
        do_enrich and not args.enrich and (args.enrich_buh or args.enrich_egrul)
    )
    # --enrich-buh / --enrich-egrul alone → only enrich, no scrape
    if (args.enrich_buh or args.enrich_egrul) and not args.enrich and not args.listen:
        do_scrape = False
    if args.enrich_only:
        do_scrape = False
    if args.export_only and not do_enrich:
        export_from_db(db)
        db.close()
        return

    try:
        if do_scrape or args.listen:
            client = make_client()
            await client.connect()
            if not await client.is_user_authorized():
                raise SystemExit("Нет сессии. Сначала: python telegram_login.py")
            if do_scrape:
                await scrape_history(client, db, limit=args.limit)

        if do_enrich:
            from parser.enrich import enrich_db

            print(f"Источники обогащения: {sources}")
            result = enrich_db(
                db,
                limit=args.enrich_limit,
                pause=args.enrich_pause,  # None → ENRICH_PAUSE из .env
                sources=sources,
            )
            print(f"Обогащение: {result}")

        export_from_db(db)

        if args.listen:
            if client is None:
                client = make_client()
                await client.connect()
            await listen_live(client, db)
    finally:
        if client is not None:
            await client.disconnect()
        db.close()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    ap = argparse.ArgumentParser(description="Парсер продажи ООО из Telegram")
    ap.add_argument("--limit", type=int, default=HISTORY_LIMIT)
    ap.add_argument("--listen", action="store_true")
    ap.add_argument("--export-only", action="store_true")
    ap.add_argument("--enrich", action="store_true", help="scrape + ЕГРЮЛ + БФО")
    ap.add_argument("--enrich-only", action="store_true", help="ЕГРЮЛ+БФО без scrape")
    ap.add_argument("--enrich-egrul", action="store_true", help="только ЕГРЮЛ")
    ap.add_argument("--enrich-buh", action="store_true", help="только БФО → K/R/U")
    ap.add_argument(
        "--enrich-limit",
        type=int,
        default=ENRICH_LIMIT,
        help=f"лимит лотов (default {ENRICH_LIMIT} из .env)",
    )
    ap.add_argument(
        "--enrich-pause",
        type=float,
        default=None,
        help=f"пауза сек (default ENRICH_PAUSE={ENRICH_PAUSE} + jitter)",
    )
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    if args.selftest:
        selftest()
        return

    asyncio.run(async_main(args))


if __name__ == "__main__":
    main()
