"""На сервере: сравнить V из Companium / Checko / Федресурс.

  python tools/probe_v_sources.py
  python tools/probe_v_sources.py 7733475417 1257700417611
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from parser.enrich.checko import checklist_from_checko, fetch_checko
from parser.enrich.companium import checklist_from_companium, fetch_companium
from parser.enrich.fedresurs import checklist_from_fedresurs, fetch_fedresurs
from parser.enrich.proxy_pool import ensure_loaded, proxy_enabled


def one(inn: str, ogrn: str) -> None:
    print(f"\n=== INN {inn} OGRN {ogrn}")
    c = fetch_companium(ogrn=ogrn, inn=inn)
    cl = checklist_from_companium(c)
    print(
        "Companium:",
        f"msgs={c.fedresurs_msgs}",
        f"V={cl.get('V_leases')!r}",
        f"note={cl.get('V_note')!r}",
        f"err={c.error!r}",
    )
    k = fetch_checko(ogrn=ogrn, inn=inn)
    cl2 = checklist_from_checko(k)
    print(
        "Checko:   ",
        f"empty={k.fedresurs_empty}",
        f"V={cl2.get('V_leases')!r}",
        f"note={cl2.get('V_note')!r}",
        f"err={k.error!r}",
    )
    f = fetch_fedresurs(inn)
    cl3 = checklist_from_fedresurs(f)
    print(
        "Fedresurs:",
        f"leases={f.lease_hits}",
        f"V={cl3.get('V_leases')!r}",
        f"note={cl3.get('V_note')!r}",
        f"O={cl3.get('O_clean')!r}",
        f"err={f.error!r}",
    )


def main() -> None:
    if proxy_enabled():
        print("proxy pool", ensure_loaded())
    args = [a for a in sys.argv[1:] if a]
    if len(args) >= 2:
        one(args[0], args[1])
        return
    for inn, ogrn in (
        ("7733475417", "1257700417611"),
        ("9727098926", "1257700054534"),
        ("9707060201", "1267700253040"),
    ):
        one(inn, ogrn)


if __name__ == "__main__":
    main()
