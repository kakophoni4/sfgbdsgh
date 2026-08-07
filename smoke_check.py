"""Проверка, что с сервера открываются нужные сайты ФНС/ЕГРЮЛ/БФО."""

from __future__ import annotations

import socket
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _dns(host: str) -> str:
    try:
        return socket.gethostbyname(host)
    except Exception as e:  # noqa: BLE001
        return f"FAIL:{e}"


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    hosts = [
        "egrul.nalog.ru",
        "bo.nalog.ru",
        "bo.nalog.gov.ru",
        "service.nalog.ru",
        "fssp.gov.ru",
        "kad.arbitr.ru",
        "fedresurs.ru",
    ]
    print("=== DNS ===")
    for h in hosts:
        print(f"  {h:24} {_dns(h)}")

    print("\n=== HTTP smoke ===")
    from parser.enrich.http_util import http_get, make_session

    session = make_session()
    urls = [
        "https://egrul.nalog.ru/",
        "https://bo.nalog.ru/",
        "https://service.nalog.ru/",
    ]
    for url in urls:
        try:
            r = http_get(session, url, allow_redirects=False, timeout=25)
            loc = ""
            try:
                loc = r.headers.get("location") or ""
            except Exception:
                pass
            print(f"  {url} → {r.status_code} loc={loc[:60]}")
        except Exception as e:  # noqa: BLE001
            print(f"  {url} → ERR {e}")

    print("\n=== ЕГРЮЛ lookup (Сбер) ===")
    from parser.enrich.egrul import lookup_company

    rec = lookup_company(inn="7707083893")
    if rec.error:
        print(f"  ERR {rec.error}")
    else:
        print(f"  OK {rec.name} inn={rec.inn} status={rec.status}")

    print("\n=== БФО lookup (Сбер) ===")
    from parser.enrich.buh import fetch_buh

    buh = fetch_buh("7707083893", pause=1.0)
    if buh.error:
        print(f"  ERR {buh.error}")
    else:
        print(f"  OK org_id={buh.org_id} years={len(buh.years)} name={buh.name}")

    print("\nГотово. Если ЕГРЮЛ/БФО = OK — сервер подходит.")


if __name__ == "__main__":
    main()
