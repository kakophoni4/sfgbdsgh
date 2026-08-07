"""Сбросить кривые хиты ЕГРЮЛ (поиск по мусорному имени / чужой ИНН).

После очистки снова:
  python run_parser.py --enrich-only --enrich-egrul --enrich-limit 0

  python tools/cleanup_bad_egrul.py
  python tools/cleanup_bad_egrul.py --apply
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import DB_PATH
from parser.db import ListingDB
from parser.enrich.egrul import _name_similar
from parser.extract import can_search_egrul_by_name, is_plausible_firm_name


def _is_bad(p: dict) -> tuple[bool, str]:
    eg = (p.get("enrich") or {}).get("egrul") or {}
    if not eg or eg.get("error"):
        return False, ""
    if not eg.get("inn"):
        return False, ""

    name = (p.get("name") or "").strip()
    # имя в payload уже могли перезаписать официальным — смотрим raw_text / seller hints
    raw = (p.get("raw_text") or "")[:300]
    # явный мусор в текущем имени
    if name and not is_plausible_firm_name(name) and not can_search_egrul_by_name(name):
        # но если имя уже ООО из реестра — ок; плохие только контакты/реклама
        if not name.upper().startswith("ООО"):
            return True, "name_not_ooo"
        if not is_plausible_firm_name(name):
            return True, "fake_or_ad_name"

    # хит по имени: в raw нет этого ИНН и имя поста не поисковое
    inn = str(eg.get("inn") or "")
    inn_in_raw = inn and inn in (p.get("raw_text") or "")
    listing_inn = (p.get("inn") or "").strip()
    # ИНН только из егрул, в посте цифр не было, а имя для поиска плохое
    if listing_inn == inn and not inn_in_raw:
        # восстановить «исходный» признак: если в тексте нет названия похожего на egrul
        eg_name = eg.get("name") or eg.get("name_full") or ""
        if eg_name and not _name_similar(name, eg_name) and not can_search_egrul_by_name(name):
            return True, "inn_not_in_post_name_mismatch"
        # «Для связи» и т.п. в начале raw
        low = raw.lower()
        if any(
            x in low[:80]
            for x in ("для связи", "пишите", "@", "добрый день", "нужна ")
        ) and not can_search_egrul_by_name(name):
            return True, "contact_line_hit"

    # сохранённый eg пришёл при bad search (имя рекламное в eg.raw query — нет поля)
    # эвристика: официальное имя есть, но payload name — реклама
    if name and not is_plausible_firm_name(name):
        return True, "payload_name_still_fake"

    return False, ""


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="реально очистить (иначе dry-run)")
    args = ap.parse_args()

    db = ListingDB(DB_PATH)
    bad: list[tuple[dict, str]] = []
    for p in db.all_payloads():
        ok, reason = _is_bad(p)
        if ok:
            bad.append((p, reason))

    print(f"Подозрительных хитов ЕГРЮЛ: {len(bad)}")
    for p, reason in bad[:40]:
        eg = (p.get("enrich") or {}).get("egrul") or {}
        print(
            f"  - {reason}: name={p.get('name')!r} inn={p.get('inn')} "
            f"eg={eg.get('name')!r} eg_inn={eg.get('inn')}"
        )
    if len(bad) > 40:
        print(f"  … ещё {len(bad) - 40}")

    if not args.apply:
        print("Dry-run. Для очистки: python tools/cleanup_bad_egrul.py --apply")
        db.close()
        return

    n = 0
    for p, reason in bad:
        enrich = dict(p.get("enrich") or {})
        eg = enrich.get("egrul") or {}
        # убрать ложный ИНН только если он совпадает с eg и не встречался в посте
        inn = (p.get("inn") or "").strip()
        if inn and inn == str(eg.get("inn") or "") and inn not in (p.get("raw_text") or ""):
            p["inn"] = ""
        enrich.pop("egrul", None)
        # связанные дыры — чтобы перепробить
        for k in ("buh", "companium", "checko"):
            block = enrich.get(k) or {}
            if block.get("inn") == eg.get("inn") or not (p.get("inn") or "").strip():
                # не трогаем buh/companium если ИНН был из поста
                pass
        cl = dict(enrich.get("checklist") or {})
        for k in list(cl.keys()):
            if k.startswith(("F_", "C_reg", "M_", "N_", "status", "I_")):
                # сброс полей от егрул — пересчитаются
                if k in {"F_address", "F_director", "C_reg_date", "M_not_liquidating",
                         "N_not_excluding", "status", "I_reliable", "I_note", "kpp"}:
                    cl.pop(k, None)
        enrich["checklist"] = cl
        enrich["egrul_cleared"] = reason
        p["enrich"] = enrich
        db.save_payload(p)
        n += 1

    print(f"Очищено: {n}. Дальше: enrich-egrul и rescore+export.")
    db.close()


if __name__ == "__main__":
    main()
