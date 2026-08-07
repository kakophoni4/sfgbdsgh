"""Сбросить только явно кривые хиты ЕГРЮЛ.

Не трогаем, если в посте есть ИНН/ОГРН или узнаваемый кусок бренда.

  python tools/cleanup_bad_egrul.py
  python tools/cleanup_bad_egrul.py --apply
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import DB_PATH
from parser.db import ListingDB
from parser.extract import is_plausible_firm_name


def _brand_tokens(eg_name: str) -> list[str]:
    t = re.sub(r"(?i)^ООО\s*", "", eg_name or "")
    t = re.sub(r"(?i)^ПРОИЗВОДСТВЕННО-КОММЕРЧЕСКАЯ\s+ФИРМА\s*", "", t)
    t = re.sub(r"[«»\"“”']", " ", t)
    parts = re.split(r"[\s\-—]+", t.upper())
    out = []
    stop = {
        "ООО",
        "И",
        "В",
        "НА",
        "С",
        "ПО",
        "ТД",
        "ПК",
        "УК",
        "НПФ",
        "СМПЦ",
        "ФИРМА",
    }
    for p in parts:
        p = p.strip()
        if len(p) < 4 or p in stop:
            continue
        if p.isdigit():
            continue
        out.append(p)
    return out


def _has_id_in_raw(p: dict, eg: dict) -> bool:
    raw = p.get("raw_text") or ""
    inn = str(eg.get("inn") or p.get("inn") or "")
    ogrn = str(eg.get("ogrn") or p.get("ogrn") or "")
    if inn and len(inn) == 10 and inn in raw:
        return True
    if ogrn and len(ogrn) >= 13 and ogrn in raw:
        return True
    return False


def _brand_in_raw(eg_name: str, raw: str) -> bool:
    up = (raw or "").upper()
    tokens = _brand_tokens(eg_name)
    if not tokens:
        return False
    # достаточно одного сильного токена бренда в тексте
    return any(tok in up for tok in tokens)


def _payload_name_is_garbage(name: str) -> bool:
    n = (name or "").strip()
    if not n:
        return False
    if not is_plausible_firm_name(n):
        return True
    low = n.lower()
    garbage = (
        "в москв",
        "москва или",
        "мос обл",
        "на осно",
        "на усн",
        "на чел",
        "уставн",
        "с эцп",
        "без смен",
        "регион:",
        "адрес:",
        "для связи",
        "добрый день",
    )
    return any(g in low for g in garbage)


def _eg_name_is_garbage(eg_name: str) -> bool:
    """Официальное имя само по себе бывает странным — ловим явный бред."""
    low = (eg_name or "").lower()
    # «ИЮЛЬ В МОСКВЕ», «ОБЛ» как результат кривого поиска
    if re.search(r"(?i)\bв москве\b", low) and "июль" in low:
        return True
    brand = re.sub(r"(?i)^ооо\s*", "", eg_name or "").strip(" «»\"'")
    if brand.upper() in {"ОБЛ", "СВЯЗИ", "МОСКВА"}:
        return True
    return False


def _is_bad(p: dict) -> tuple[bool, str]:
    eg = (p.get("enrich") or {}).get("egrul") or {}
    if not eg or eg.get("error") or not eg.get("inn"):
        return False, ""

    eg_name = (eg.get("name") or eg.get("name_full") or "").strip()
    name = (p.get("name") or "").strip()
    raw = p.get("raw_text") or ""

    # 1) В посте есть ИНН/ОГРН — хит по ключу, оставляем (имя починим)
    if _has_id_in_raw(p, eg):
        if _payload_name_is_garbage(name):
            return True, "fix_name_keep_inn"
        return False, ""

    # 2) Явно мусорное официальное имя после кривого поиска
    if _eg_name_is_garbage(eg_name):
        return True, "garbage_eg_name"

    # 3) В посте есть кусок бренда (РУНАР / ЭГГЕРТ / СПЕЦЗАЩИТА) — ок
    if eg_name and _brand_in_raw(eg_name, raw):
        if _payload_name_is_garbage(name):
            return True, "fix_name_keep_inn"
        return False, ""

    # 4) Нет ни ИНН/ОГРН, ни бренда в посте — чужой хит
    return True, "no_id_no_brand_in_post"


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    db = ListingDB(DB_PATH)
    bad: list[tuple[dict, str]] = []
    for p in db.all_payloads():
        ok, reason = _is_bad(p)
        if ok:
            bad.append((p, reason))

    print(f"Подозрительных хитов ЕГРЮЛ: {len(bad)}")
    for p, reason in bad[:60]:
        eg = (p.get("enrich") or {}).get("egrul") or {}
        print(
            f"  - {reason}: name={p.get('name')!r} inn={p.get('inn')} "
            f"eg={eg.get('name')!r} eg_inn={eg.get('inn')}"
        )
    if len(bad) > 60:
        print(f"  … ещё {len(bad) - 60}")

    if not args.apply:
        print("Dry-run. Для очистки: python tools/cleanup_bad_egrul.py --apply")
        db.close()
        return

    n_clear = 0
    n_fix = 0
    for p, reason in bad:
        enrich = dict(p.get("enrich") or {})
        eg = dict(enrich.get("egrul") or {})

        if reason == "fix_name_keep_inn":
            official = eg.get("name") or eg.get("name_full") or ""
            if official:
                if not str(official).upper().startswith("ООО"):
                    official = f"ООО «{official}»"
                p["name"] = official
                n_fix += 1
                db.save_payload(p)
            continue

        inn = (p.get("inn") or "").strip()
        eg_inn = str(eg.get("inn") or "")
        raw = p.get("raw_text") or ""
        # сбрасываем ИНН только если его не было в посте
        if inn and inn == eg_inn and inn not in raw:
            p["inn"] = ""
        enrich.pop("egrul", None)
        cl = dict(enrich.get("checklist") or {})
        for k in (
            "F_address",
            "F_director",
            "C_reg_date",
            "M_not_liquidating",
            "N_not_excluding",
            "status",
            "I_reliable",
            "I_note",
            "kpp",
        ):
            cl.pop(k, None)
        enrich["checklist"] = cl
        enrich["egrul_cleared"] = reason
        p["enrich"] = enrich
        db.save_payload(p)
        n_clear += 1

    print(f"Сброшено хитов: {n_clear} | починено имён: {n_fix}")
    print("Дальше: enrich-egrul и rescore+export.")
    db.close()


if __name__ == "__main__":
    main()
