"""Пул прокси из URL-списка (asocks whitelist, host:port).

Авторизация по белому IP сервера. Список кэшируется на диск и периодически
обновляется. При мёртвом прокси / капче — следующий.
"""
from __future__ import annotations

import random
import re
import time
import urllib.request
from pathlib import Path
from typing import Any

_HOSTPORT = re.compile(r"^(\d{1,3}(?:\.\d{1,3}){3}):(\d{2,5})$")

_state: dict[str, Any] = {
    "proxies": [],  # list[str] "http://ip:port"
    "idx": 0,
    "loaded_at": 0.0,
    "bad": set(),  # str
    "current": "",
}


def _cfg() -> tuple[str, float, int, Path]:
    try:
        from config import (
            DATA_DIR,
            ENRICH_PROXY_LIST_TTL,
            ENRICH_PROXY_LIST_URL,
            ENRICH_PROXY_TRIES,
        )

        url = (ENRICH_PROXY_LIST_URL or "").strip()
        ttl = float(ENRICH_PROXY_LIST_TTL or 900)
        tries = int(ENRICH_PROXY_TRIES or 8)
        cache = Path(DATA_DIR) / "proxy_list_cache.txt"
        return url, ttl, tries, cache
    except Exception:
        import os
        from pathlib import Path as P

        root = P(__file__).resolve().parents[2]
        url = os.getenv("ENRICH_PROXY_LIST_URL", "").strip()
        ttl = float(os.getenv("ENRICH_PROXY_LIST_TTL", "900"))
        tries = int(os.getenv("ENRICH_PROXY_TRIES", "8"))
        return url, ttl, tries, root / "data" / "proxy_list_cache.txt"


def _normalize_line(line: str) -> str:
    s = (line or "").strip()
    if not s or s.startswith("#"):
        return ""
    if "://" in s:
        # http://ip:port or http://user:pass@ip:port
        return s if s.startswith("http") else "http://" + s.split("://", 1)[-1]
    if _HOSTPORT.match(s):
        return f"http://{s}"
    # ip:port:user:pass — на всякий
    parts = s.split(":")
    if len(parts) == 4 and _HOSTPORT.match(f"{parts[0]}:{parts[1]}"):
        return f"http://{parts[2]}:{parts[3]}@{parts[0]}:{parts[1]}"
    return ""


def _parse_body(text: str) -> list[str]:
    out: list[str] = []
    for line in text.splitlines():
        u = _normalize_line(line)
        if u:
            out.append(u)
    return out


def _download(url: str, cache: Path) -> list[str]:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "firm-parser/1.0", "Accept": "text/plain,*/*"},
    )
    with urllib.request.urlopen(req, timeout=90) as resp:
        raw = resp.read()
    text = raw.decode("utf-8", "replace")
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_bytes(raw)
    proxies = _parse_body(text)
    random.shuffle(proxies)
    return proxies


def _load_cache(cache: Path) -> list[str]:
    if not cache.exists():
        return []
    text = cache.read_text(encoding="utf-8", errors="replace")
    proxies = _parse_body(text)
    random.shuffle(proxies)
    return proxies


def ensure_loaded(*, force: bool = False) -> int:
    url, ttl, _tries, cache = _cfg()
    now = time.time()
    if (
        not force
        and _state["proxies"]
        and now - float(_state["loaded_at"]) < ttl
    ):
        return len(_state["proxies"])

    proxies: list[str] = []
    if url:
        try:
            proxies = _download(url, cache)
        except Exception:
            proxies = _load_cache(cache)
    elif cache.exists():
        proxies = _load_cache(cache)

    # fallback: одиночный ENRICH_PROXY
    if not proxies:
        try:
            from config import ENRICH_PROXY

            one = (ENRICH_PROXY or "").strip()
        except Exception:
            import os

            one = os.getenv("ENRICH_PROXY", "").strip()
        if one:
            u = _normalize_line(one) or (
                one if "://" in one else f"http://{one}"
            )
            proxies = [u]

    _state["proxies"] = proxies
    _state["idx"] = 0
    _state["loaded_at"] = now
    _state["bad"] = set()
    if proxies and not _state["current"]:
        _state["current"] = proxies[0]
    return len(proxies)


def current_proxy() -> str:
    ensure_loaded()
    cur = str(_state.get("current") or "")
    if cur and cur not in _state["bad"]:
        return cur
    return rotate_proxy()


def rotate_proxy() -> str:
    ensure_loaded()
    proxies: list[str] = _state["proxies"]
    if not proxies:
        _state["current"] = ""
        return ""
    n = len(proxies)
    for _ in range(n):
        i = int(_state["idx"]) % n
        _state["idx"] = i + 1
        cand = proxies[i]
        if cand not in _state["bad"]:
            _state["current"] = cand
            return cand
    # все помечены bad — сброс bad и новая попытка с кэша/URL
    _state["bad"] = set()
    ensure_loaded(force=True)
    proxies = _state["proxies"]
    if not proxies:
        _state["current"] = ""
        return ""
    _state["current"] = proxies[0]
    _state["idx"] = 1
    return _state["current"]


def mark_bad(proxy: str | None = None, *, reason: str = "") -> None:
    p = proxy or str(_state.get("current") or "")
    if not p:
        return
    bad: set = _state["bad"]
    bad.add(p)
    # не раздувать: если bad > половины пула — очистить старые
    proxies = _state["proxies"]
    if proxies and len(bad) > max(50, len(proxies) // 2):
        _state["bad"] = {p}
    _ = reason


def proxy_enabled() -> bool:
    url, _, _, cache = _cfg()
    if url or cache.exists():
        return True
    try:
        from config import ENRICH_PROXY

        return bool((ENRICH_PROXY or "").strip())
    except Exception:
        return False


def max_tries() -> int:
    _, _, tries, _ = _cfg()
    return max(1, min(tries, 30))


def is_proxy_dead_error(exc: BaseException | str) -> bool:
    msg = str(exc).lower()
    keys = (
        "connect tunnel failed",
        "proxy",
        "timed out",
        "timeout",
        "connection refused",
        "connection reset",
        "failed to perform",
        "curl: (7)",
        "curl: (28)",
        "curl: (56)",
        "407",
        "502",
        "503",
        "empty reply",
        "tunnel",
    )
    return any(k in msg for k in keys)
