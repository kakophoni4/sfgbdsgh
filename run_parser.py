"""
Запуск парсера продажи компаний.

Примеры:
  python run_parser.py --enrich-only --enrich-limit 20
  python run_parser.py --enrich-kad --enrich-fssp --enrich-limit 20
  python run_parser.py --enrich-fedresurs --enrich-limit 20
  python run_parser.py --rescore
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
            "✅ ООО «Новый Алгоритм»\nИНН 7733475417\nРегистрация 19.09.2025 г.\n\nОСНО\n🟢 Зеленая по ЗСК\n💵 Цена 90 т.р.",
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
        print(f"expect={expect} got={len(got)}")
        if len(got) != expect:
            ok = False
    from parser.enrich.egrul import status_flags

    assert status_flags("1")["status"] == "действующая"
    assert status_flags("1")["M"] == "ДА"
    print("status_flags OK")

    from parser.enrich.fedresurs import FedresursReport, checklist_from_fedresurs
    from parser.enrich.unreliable import check_unreliable_from_egrul, checklist_from_unreliable

    cl_o = checklist_from_fedresurs(
        FedresursReport(
            inn="9710056741",
            status="введено наблюдение (банкротство)",
            is_bankrupt=True,
            lease_hits=None,
            lease_note="blocked",
        )
    )
    assert cl_o["O_clean"] == "НЕТ"
    assert cl_o["V_leases"] == "ПРОВЕРИТЬ"
    cl_i = checklist_from_unreliable(
        check_unreliable_from_egrul(
            {"inn": "1", "address": "г. Москва, сведения недостоверны", "error": ""}
        )
    )
    assert cl_i["I_reliable"] == "НЕТ"
    print("O/I checklist OK")
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
    explicit = []
    if args.enrich_egrul:
        explicit.append("egrul")
    if args.enrich_buh:
        explicit.append("buh")
    if args.enrich_kad:
        explicit.append("kad")
    if args.enrich_fssp:
        explicit.append("fssp")
    if args.enrich_fedresurs:
        explicit.append("fedresurs")
    if args.enrich_unreliable:
        explicit.append("unreliable")

    if explicit and not args.enrich and not args.enrich_only:
        return explicit
    if args.enrich or args.enrich_only:
        if explicit:
            return explicit
        return ["egrul", "buh", "kad", "fssp", "fedresurs", "unreliable"]
    return []


async def async_main(args: argparse.Namespace) -> None:
    db = ListingDB(DB_PATH)
    client = None
    sources = resolve_sources(args)
    do_enrich = bool(sources)
    only_flags = bool(
        args.enrich_buh
        or args.enrich_egrul
        or args.enrich_kad
        or args.enrich_fssp
        or args.enrich_fedresurs
        or args.enrich_unreliable
    )
    do_scrape = True
    if args.export_only or args.enrich_only or args.rescore:
        do_scrape = False
    if only_flags and not args.enrich and not args.listen:
        do_scrape = False

    if args.export_only and not do_enrich and not args.rescore:
        export_from_db(db)
        db.close()
        return

    try:
        if args.rescore:
            from parser.enrich.pipeline import rescore_db

            print("Rescore:", rescore_db(db))
            export_from_db(db)
            if not do_enrich and not args.listen:
                return

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
                pause=args.enrich_pause,
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
    ap.add_argument("--rescore", action="store_true", help="пересчёт M/N/score без сети")
    ap.add_argument("--enrich", action="store_true", help="scrape + все enrich")
    ap.add_argument("--enrich-only", action="store_true", help="все enrich без scrape")
    ap.add_argument("--enrich-egrul", action="store_true")
    ap.add_argument("--enrich-buh", action="store_true")
    ap.add_argument("--enrich-kad", action="store_true", help="арбитраж КАД → P")
    ap.add_argument("--enrich-fssp", action="store_true", help="ФССП → L")
    ap.add_argument(
        "--enrich-fedresurs",
        action="store_true",
        help="Федресурс/ЕФРСБ → O, лизинг → V",
    )
    ap.add_argument(
        "--enrich-unreliable",
        action="store_true",
        help="недостоверки ЕГРЮЛ → I (без сети, по карточке)",
    )
    ap.add_argument("--enrich-limit", type=int, default=ENRICH_LIMIT)
    ap.add_argument("--enrich-pause", type=float, default=None)
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    if args.selftest:
        selftest()
        return

    asyncio.run(async_main(args))


if __name__ == "__main__":
    main()
