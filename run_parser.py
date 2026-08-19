"""
Запуск парсера продажи компаний.

Примеры:
  python run_parser.py --enrich-only --enrich-limit 20
  python run_parser.py --enrich-kad --enrich-fssp --enrich-limit 20
  python run_parser.py --enrich-fedresurs --enrich-limit 20
  python run_parser.py --enrich-core --enrich-limit 40
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

from config import (
    DB_PATH,
    ENRICH_LIMIT,
    ENRICH_PAUSE,
    EXPORT_PATH,
    HISTORY_LIMIT,
    SINCE_DAYS,
)
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
        if got and got[0].source != "группа продаж":
            print("bad source sales", got[0].source)
            ok = False

    inn_q = parse_message(
        "7327095420",
        chat_id=-5451292146,
        message_id=794,
        sender="me",
        msg_date="2026-08-12T21:38:44+00:00",
    )
    print(f"inn_queue expect=1 got={len(inn_q)}")
    if (
        len(inn_q) != 1
        or inn_q[0].inn != "7327095420"
        or inn_q[0].source != "чат проверка"
    ):
        ok = False
        print("inn_queue FAIL", inn_q)

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
    assert cl_o["O_clean"] == "есть банкротство"
    assert "V_leases" not in cl_o  # 451/blocked — не затираем V агрегаторов
    cl_ok = checklist_from_fedresurs(
        FedresursReport(inn="1", status="Действующее", is_bankrupt=False, lease_hits=0)
    )
    assert cl_ok["O_clean"] == "нет банкротства"
    assert cl_ok["V_leases"] == "нет лизинга/залогов"

    from parser.enrich.companium import CompaniumReport, checklist_from_companium

    cl_c = checklist_from_companium(
        CompaniumReport(
            ogrn="1234567890123",
            court_cases=0,
            enforcements=0,
            unreliable=False,
            fedresurs_msgs=0,
        )
    )
    assert cl_c["P_court_cases"] == "нет дел"
    assert cl_c["L_debts_il"] == "нет долгов/ИЛ"
    assert cl_c["I_reliable"] == "ДА"
    assert cl_c["V_leases"] == "нет лизинга/залогов"
    cl_c2 = checklist_from_companium(
        CompaniumReport(
            ogrn="1234567890123",
            court_cases=1,
            enforcements=0,
            unreliable=False,
            fedresurs_msgs=4,
        )
    )
    assert cl_c2["V_leases"] == "есть записи"
    assert "fedresurs" in (cl_c2.get("V_link") or "")
    print("companium checklist OK")

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


def export_from_db(
    db: ListingDB,
    *,
    to_gsheets: bool = False,
    to_apps_script: bool = False,
    to_crm: bool = False,
) -> Path:
    from parser.export_apps_script import build_export_body, export_apps_script
    from parser.export_crm import ingest_crm, write_crm_xlsx
    from parser.export_fingerprint import (
        fingerprint,
        load_fingerprint,
        save_fingerprint,
    )

    print("Экспорт: читаю базу…", flush=True)
    payloads = mark_duplicates(db.all_payloads())
    uniq = [p for p in payloads if not p.get("is_duplicate")]
    print(
        f"Экспорт: лотов={len(payloads)} уникальных={len(uniq)} — собираю таблицу…",
        flush=True,
    )

    body, skipped = build_export_body(uniq, skip_duplicates=False)
    fp = fingerprint(body)
    if fp and fp == load_fingerprint():
        print(
            f"Экспорт: без изменений (fingerprint={fp[:12]}…) — "
            f"Excel/CRM не перезаписываю | уникальных={len(uniq)} | "
            f"stats={db.stats()}"
        )
        return EXPORT_PATH

    # аннотации дублей — одним commit, не 2000 fsync
    print("Экспорт: сохраняю аннотации в БД (batch)…", flush=True)
    db.save_payloads(payloads)

    print("Экспорт: пишу Excel…", flush=True)
    path = export_xlsx(uniq, EXPORT_PATH, skip_duplicates=False)
    print(
        f"Excel: {path} | всего={len(payloads)} | уникальных={len(uniq)} | "
        f"stats={db.stats()}"
    )

    print("Экспорт: пишу CRM xlsx…", flush=True)
    crm_path, _, _ = write_crm_xlsx(uniq, skip_duplicates=False)
    if to_crm:
        print("Экспорт: заливка в Lavok CRM…", flush=True)
        ingest_crm(crm_path)
    elif to_apps_script:
        export_apps_script(
            uniq, skip_duplicates=False, body=body, skipped=skipped
        )
    elif to_gsheets:
        from parser.export_gsheets import export_gsheets

        export_gsheets(uniq, skip_duplicates=False)

    save_fingerprint(fp)
    print(f"Экспорт: обновлено (fingerprint={fp[:12]}…)", flush=True)
    return path


def resolve_sources(args: argparse.Namespace) -> list[str]:
    if getattr(args, "enrich_core", False):
        return [
            "egrul",
            "buh",
            "companium",
            "checko",
            "fedresurs",
            "saby",
            "unreliable",
        ]

    explicit = []
    if args.enrich_egrul:
        explicit.append("egrul")
    if args.enrich_buh:
        explicit.append("buh")
    if args.enrich_companium:
        explicit.append("companium")
    if args.enrich_checko:
        explicit.append("checko")
    if args.enrich_saby:
        explicit.append("saby")
    if args.enrich_kad:
        explicit.append("kad")
    if args.enrich_fssp:
        explicit.append("fssp")
    if args.enrich_fedresurs:
        explicit.append("fedresurs")
    if args.enrich_unreliable:
        explicit.append("unreliable")
    if getattr(args, "enrich_zsk_bot", False):
        explicit.append("zsk_bot")

    if explicit and not args.enrich and not args.enrich_only:
        return explicit
    if args.enrich or args.enrich_only:
        if explicit:
            return explicit
        return [
            "egrul",
            "buh",
            "companium",
            "checko",
            "fedresurs",
            "saby",
            "unreliable",
        ]
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
        or args.enrich_companium
        or args.enrich_checko
        or args.enrich_saby
        or getattr(args, "enrich_zsk_bot", False)
        or getattr(args, "enrich_core", False)
    )
    do_scrape = True
    if args.export_only or args.enrich_only or args.rescore:
        do_scrape = False
    if only_flags and not args.enrich and not args.listen:
        do_scrape = False

    to_sheets = bool(getattr(args, "export_gsheets", False))
    to_apps = bool(getattr(args, "export_apps_script", False))
    to_crm = bool(getattr(args, "export_crm", False))

    if args.export_only and not do_enrich and not args.rescore:
        export_from_db(
            db, to_gsheets=to_sheets, to_apps_script=to_apps, to_crm=to_crm
        )
        db.close()
        return

    try:
        if args.rescore:
            from parser.enrich.pipeline import rescore_db

            print("Rescore:", rescore_db(db))
            export_from_db(
                db, to_gsheets=to_sheets, to_apps_script=to_apps, to_crm=to_crm
            )
            if not do_enrich and not args.listen:
                return

        if do_scrape or args.listen:
            client = make_client()
            await client.connect()
            if not await client.is_user_authorized():
                raise SystemExit("Нет сессии. Сначала: python telegram_login.py")
            if do_scrape:
                await scrape_history(
                    client,
                    db,
                    limit=args.limit,
                    since_days=getattr(args, "since_days", None),
                )

        if do_enrich:
            from parser.enrich import enrich_db
            from parser.enrich.pipeline import enrich_zsk_bot_db

            print(f"Источники обогащения: {sources}", flush=True)
            # ЗСК-бот отдельно: Telethon + свой event loop в потоке
            if sources == ["zsk_bot"]:
                result = enrich_zsk_bot_db(
                    db,
                    limit=args.enrich_limit,
                    pause=args.enrich_pause if args.enrich_pause is not None else 3.0,
                )
            else:
                result = enrich_db(
                    db,
                    limit=args.enrich_limit,
                    pause=args.enrich_pause,
                    sources=sources,
                )
            print(f"Обогащение: {result}", flush=True)

        export_from_db(
            db, to_gsheets=to_sheets, to_apps_script=to_apps, to_crm=to_crm
        )

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
    ap.add_argument(
        "--limit",
        type=int,
        default=HISTORY_LIMIT,
        help="макс. сообщений (с --since-days поднимается автоматически)",
    )
    ap.add_argument(
        "--since-days",
        type=int,
        default=SINCE_DAYS,
        help="брать сообщения только за последние N дней (напр. 30 = месяц)",
    )
    ap.add_argument("--listen", action="store_true")
    ap.add_argument("--export-only", action="store_true")
    ap.add_argument(
        "--export-gsheets",
        action="store_true",
        help="выгрузка в Sheets через service account (нужен Google Cloud)",
    )
    ap.add_argument(
        "--export-apps-script",
        action="store_true",
        help="выгрузка в Sheets через Apps Script (устарело; лучше --export-crm)",
    )
    ap.add_argument(
        "--export-crm",
        action="store_true",
        help="xlsx → Lavok CRM (LAVOK_INGEST_TOKEN / LAVOK_INGEST_URL)",
    )
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
    ap.add_argument(
        "--enrich-companium",
        action="store_true",
        help="Companium.ru → P/L/I (по ОГРН)",
    )
    ap.add_argument(
        "--enrich-checko",
        action="store_true",
        help="Checko.ru запасной → P/L/I/V",
    )
    ap.add_argument(
        "--enrich-saby",
        action="store_true",
        help="Saby/СБИС запасной → I",
    )
    ap.add_argument(
        "--enrich-core",
        action="store_true",
        help="ядро + запасные: ЕГРЮЛ БФО Companium Checko Федресурс Saby",
    )
    ap.add_argument(
        "--enrich-zsk-bot",
        action="store_true",
        help="ЗСК через Telegram @zskbenefitsarbot по ИНН",
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
