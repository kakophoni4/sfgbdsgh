"""
Проверка всех источников обогащения + статус запасных цепочек.

  python check_sources.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# тестовые ключи
INN_OK = "7709613803"  # ООО Маркет 7
OGRN_OK = "1057747184648"
INN_BANK = "7707083893"  # Сбер — много судов


def _row(name: str, ok: bool, detail: str, soft: bool = False) -> None:
    if ok:
        mark = "OK  "
    elif soft:
        mark = "SOFT"
    else:
        mark = "FAIL"
    print(f"  [{mark}] {name:16} {detail}")


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    print("=== Источники (живой smoke) ===\n")

    # ЕГРЮЛ
    try:
        from parser.enrich.egrul import lookup_company

        r = lookup_company(inn=INN_OK)
        _row("ЕГРЮЛ", not r.error and bool(r.inn), f"inn={r.inn} status={r.status!r} err={r.error}")
    except Exception as e:
        _row("ЕГРЮЛ", False, str(e))

    # БФО
    try:
        from parser.enrich.buh import fetch_buh

        r = fetch_buh(INN_OK, pause=0.5)
        _row("БФО", not r.error and bool(r.years), f"years={len(r.years)} err={r.error}")
    except Exception as e:
        _row("БФО", False, str(e))

    # Федресурс
    try:
        from parser.enrich.fedresurs import fetch_fedresurs

        r = fetch_fedresurs(INN_OK)
        _row(
            "Федресурс",
            r.is_bankrupt is not None and not r.error,
            f"bankrupt={r.is_bankrupt} status={r.status!r} err={r.error}",
        )
    except Exception as e:
        _row("Федресурс", False, str(e))

    # Companium
    try:
        from parser.enrich.companium import fetch_companium

        r = fetch_companium(ogrn=OGRN_OK, inn=INN_OK)
        hard_ok = r.court_cases is not None and not r.error
        soft = bool(r.error) and (
            "recaptcha" in r.error or "captcha" in r.error or "browser_" in r.error
        )
        _row(
            "Companium",
            hard_ok,
            f"P={r.court_cases} L={r.enforcements} I={r.unreliable} err={r.error}",
            soft=soft,
        )
    except Exception as e:
        _row("Companium", False, str(e))

    # Checko
    try:
        from parser.enrich.checko import fetch_checko

        r = fetch_checko(ogrn=OGRN_OK, inn=INN_OK)
        hard_ok = (r.court_cases is not None or r.enforcements is not None) and not r.error
        soft = bool(r.error) and ("captcha" in r.error or "429" in r.error)
        _row(
            "Checko",
            hard_ok,
            f"P={r.court_cases} L={r.enforcements} I={r.unreliable} err={r.error}",
            soft=soft,
        )
    except Exception as e:
        _row("Checko", False, str(e))

    # Saby
    try:
        from parser.enrich.saby import fetch_saby

        r = fetch_saby(INN_OK)
        _row(
            "Saby/СБИС",
            r.unreliable is not None,
            f"unreliable={r.unreliable} err={r.error}",
        )
    except Exception as e:
        _row("Saby/СБИС", False, str(e))

    # КАД
    try:
        from parser.enrich.kad import fetch_kad

        r = fetch_kad(INN_OK)
        ok = not r.error and r.cases_found is not None
        _row(
            "КАД",
            ok,
            f"err={r.error} n={r.cases_found}",
            soft=bool(r.error),
        )
    except Exception as e:
        _row("КАД", False, str(e))

    # ФССП
    try:
        from parser.enrich.fssp import fetch_fssp

        r = fetch_fssp(INN_OK)
        ok = r.proceedings is not None and not r.error
        _row(
            "ФССП",
            ok,
            f"n={r.proceedings} err={r.error}",
            soft=bool(r.error),
        )
    except Exception as e:
        _row("ФССП", False, str(e))

    print(
        """
=== Запасные цепочки (как в pipeline) ===
  P суды:     Companium → Checko → КАД
  L долги:    Companium → Checko → ФССП
  I недост.:  Companium → Checko → Saby → ЕГРЮЛ-маркеры
  O банкрот:  Федресурс → (Companium/Checko текст)
  V лизинг:   Федресурс публикации → Companium/Checko
  K/R/U:      БФО (без запасного бесплатного)
  M/N:        ЕГРЮЛ

Команда ядра:
  python run_parser.py --enrich-core --enrich-limit 40
"""
    )


if __name__ == "__main__":
    main()
