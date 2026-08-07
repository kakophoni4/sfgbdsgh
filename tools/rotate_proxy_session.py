"""Сменить hold-session в ENRICH_PROXY → новый мобильный IP.

Usage:
  python tools/rotate_proxy_session.py
  python tools/rotate_proxy_session.py --test
"""
from __future__ import annotations

import argparse
import re
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

ENV = ROOT / ".env"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--test", action="store_true", help="проверить новый IP и Companium")
    args = ap.parse_args()

    text = ENV.read_text(encoding="utf-8") if ENV.exists() else ""
    m = re.search(r"^ENRICH_PROXY=(.+)$", text, re.M)
    if not m:
        print("В .env нет ENRICH_PROXY")
        raise SystemExit(1)
    old = m.group(1).strip().strip('"').strip("'")
    new_sess = secrets.token_hex(6)
    if "session-" not in old:
        print("В ENRICH_PROXY нет session-… — нечего ротировать")
        raise SystemExit(1)
    new = re.sub(r"session-[A-Za-z0-9]+", f"session-{new_sess}", old, count=1)
    ENV.write_text(text.replace(m.group(0), f"ENRICH_PROXY={new}"), encoding="utf-8")
    print("OK новая сессия:", f"session-{new_sess}")
    print("host:", new.split("@")[-1] if "@" in new else "?")

    if args.test:
        # перечитать config
        import importlib

        import config

        importlib.reload(config)
        from parser.enrich.http_util import http_get, make_session

        s = make_session({"Accept": "application/json"}, use_proxy=True)
        r = http_get(s, "https://api.ipify.org?format=json", timeout=40)
        print("exit_ip:", getattr(r, "status_code", "?"), (getattr(r, "text", "") or "")[:80])
        from parser.enrich.companium import fetch_companium, human_dossier

        c = fetch_companium(ogrn="1257700417611", inn="7733475417")
        print(c.error or human_dossier(c))


if __name__ == "__main__":
    main()
