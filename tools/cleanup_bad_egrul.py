"""Сбросить кривые хиты ЕГРЮЛ (поиск по мусорному имени / чужой ИНН).

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
from parser.enrich.egrul import _name_similar
from parser.extract import can_search_egrul_by_name, is_plausible_firm_name


def _brand(s: str) -> str:
    t = re.sub(r"(?i)^ООО\s*", "", s or "")
    t = re.sub(r"[«»\"“”']", "", t).strip().upper()
    return t


def _geo_or_ad(s: str) -> bool:
    low = (s or "").lower()
    keys = (
        "в москв",
        "в спб",
        "для связи",
        "добрый день",
        "нужна ",
        "с историей",
        "большими оборот",
        "цена ",
        "на усн",
        "на осно",
    )
    return any(k in low for k in keys)


def _is_bad(p: dict) -> tuple[bool, str]:
    eg = (p.get("enrich") or {}).get("egrul") or {}
    if not eg or eg.get("error") or not eg.get("inn"):
        return False, ""

    name = (p.get("name") or "").strip()
    raw = p.get("raw_text") or ""
    inn = str(eg.get("inn") or "")
    inn_in_raw = bool(inn and inn in raw)
    eg_name = (eg.get("name") or eg.get("name_full") or "").strip()
    brand = _brand(eg_name)

    # ИНН реально был в посте — ЕГРЮЛ по ИНН ок; только починить имя
    if inn_in_raw:
        if name and not is_plausible_firm_name(name):
            return True, "fix_name_keep_inn"
        return False, ""

    # ИНН не из поста → хит только по имени. Бренд ЕГРЮЛ должен быть в тексте.
    if brand and len(brand) >= 4 and brand not in raw.upper():
        return True, "eg_name_absent_in_post"

    if _geo_or_ad(name) or _geo_or_ad(raw[:100]):
        return True, "geo_or_ad_name_hit"

    if name and not is_plausible_firm_name(name):
        if not name.upper().startswith("ООО"):
            return True, "name_not_ooo"
        return True, "fake_or_ad_name"

    # имя уже официальное, но для поиска такое не годилось бы (короткое общее)
    if eg_name and not can_search_egrul_by_name(
        eg_name if eg_name.upper().startswith("ООО") else f"ООО «{eg_name}»"
    ):
        # и в посте нет явного ООО+бренд
        if not re.search(rf"(?i)ООО\s*[«\"']?{_brand(eg_name)}", raw):
            return True, "weak_name_hit_without_post_brand"

    if name and eg_name and not _name_similar(name, eg_name) and not inn_in_raw:
        if not can_search_egrul_by_name(name):
            return True, "name_mismatch_no_inn_in_post"

    return False, ""


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
    for p, reason in bad[:50]:
        eg = (p.get("enrich") or {}).get("egrul") or {}
        print(
            f"  - {reason}: name={p.get('name')!r} inn={p.get('inn')} "
            f"eg={eg.get('name')!r} eg_inn={eg.get('inn')}"
        )
    if len(bad) > 50:
        print(f"  … ещё {len(bad) - 50}")

    if not args.apply:
        print("Dry-run. Для очистки: python tools/cleanup_bad_egrul.py --apply")
        db.close()
        return

    n_clear = 0
    n_fix_name = 0
    for p, reason in bad:
        enrich = dict(p.get("enrich") or {})
        eg = dict(enrich.get("egrul") or {})

        if reason == "fix_name_keep_inn":
            # ИНН верный — только подставить официальное имя
            official = eg.get("name") or eg.get("name_full") or ""
            if official:
                if not str(official).upper().startswith("ООО"):
                    official = f"ООО «{official}»"
                p["name"] = official
                n_fix_name += 1
                db.save_payload(p)
            continue

        inn = (p.get("inn") or "").strip()
        if inn and inn == str(eg.get("inn") or "") and inn not in (p.get("raw_text") or ""):
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

    print(f"Сброшено хитов: {n_clear} | починено имён (ИНН сохранён): {n_fix_name}")
    print("Дальше: enrich-egrul и rescore+export.")
    db.close()


if __name__ == "__main__":
    main()
