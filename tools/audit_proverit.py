"""Аудит полей ПРОВЕРИТЬ / пустых: баг или реально нет данных.

Usage (на сервере):
  cd C:\\firmy
  python tools/audit_proverit.py
  python tools/audit_proverit.py --sample 5
"""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
import sys

sys.path.insert(0, str(ROOT))

from config import DB_PATH  # noqa: E402
from parser.db import ListingDB  # noqa: E402

FIELDS = (
    ("P_court_cases", "P_note", "P_link"),
    ("L_debts_il", "L_note", "L_link"),
    ("O_clean", "O_note", "O_link"),
    ("V_leases", "V_note", "V_link"),
    ("I_reliable", "I_note", ""),
)

# note → вердикт для человека
KNOWN = {
    "publications_blocked_451": "НЕ БАГ: Федресурс режет /publications (451). O ок, лизинг неизвестен → открой V_link",
    "publications_http_": "НЕ БАГ: публикации Федресурса HTTP-ошибка → открой V_link",
    "Companium: captcha": "НЕ БАГ: капча Companium → повтор с паузой или Checko/руками",
    "Companium: blocked": "НЕ БАГ: блок Companium",
    "Checko:": "смотри note; если captcha/429 — НЕ БАГ, иначе возможен баг парсинга",
    "публикации недоступны": "НЕ БАГ: лента сообщений недоступна",
    "число дел не разобрано": "ВОЗМОЖЕН БАГ: страница открылась, счётчик не распарсили",
    "ФССП не разобрано": "ВОЗМОЖЕН БАГ: страница открылась, ФССП не распарсили",
    "parse_empty": "ВОЗМОЖЕН БАГ или пустая карточка — открой ссылку",
}


def _verdict(note: str) -> str:
    n = note or ""
    for key, msg in KNOWN.items():
        if key in n:
            return msg
    if not n:
        return "нет note — смотри ссылку; если пусто в UI = реально пусто"
    return f"смотри note/ссылку: {n[:120]}"


def _is_gap(v: Any) -> bool:
    return v is None or v in {"", "ПРОВЕРИТЬ"}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=3, help="примеров на причину")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    db = ListingDB(DB_PATH)
    seen_inn: set[str] = set()
    by_field: dict[str, Counter] = defaultdict(Counter)
    samples: dict[str, list[dict[str, Any]]] = defaultdict(list)
    totals = Counter()

    for p in db.all_payloads():
        inn = (p.get("inn") or "").strip()
        if not inn or inn in seen_inn:
            continue
        seen_inn.add(inn)
        cl = (p.get("enrich") or {}).get("checklist") or {}
        if not cl:
            continue
        for field, note_k, link_k in FIELDS:
            val = cl.get(field)
            if not _is_gap(val):
                continue
            note = str(cl.get(note_k) or "")
            reason = note.split(":")[0].strip() if note else (val or "empty")
            if "publications_blocked_451" in note:
                reason = "publications_blocked_451"
            elif "publications_http_" in note:
                reason = note
            elif note.startswith("Companium:"):
                reason = note[:80]
            elif note.startswith("Checko:"):
                reason = note[:80]
            elif note.startswith("Федресурс:"):
                reason = note[:80]
            key = f"{field}|{reason or '(no note)'}"
            by_field[field][reason or "(no note)"] += 1
            totals[field] += 1
            if len(samples[key]) < args.sample:
                samples[key].append(
                    {
                        "inn": inn,
                        "name": p.get("name") or cl.get("B_name") or "",
                        "value": val,
                        "note": note,
                        "link": cl.get(link_k) if link_k else "",
                        "verdict": _verdict(note),
                    }
                )

    print(f"Уникальных с ИНН: {len(seen_inn)}")
    print("Поля с ПРОВЕРИТЬ/пусто:")
    for field, _note, _link in FIELDS:
        print(f"  {field}: {totals[field]}")
        for reason, n in by_field[field].most_common(12):
            print(f"    [{n}] {reason}")
            k = f"{field}|{reason}"
            for s in samples.get(k, []):
                print(f"       INN {s['inn']} | {s['verdict']}")
                if s["link"]:
                    print(f"         {s['link']}")
                if s["note"]:
                    print(f"         note: {s['note']}")

    if args.json:
        out = {
            "totals": dict(totals),
            "by_field": {f: dict(c) for f, c in by_field.items()},
            "samples": samples,
        }
        print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
