from __future__ import annotations

from typing import Any
from urllib.parse import quote, urlparse, urlunparse


def _normalize_proxy(url: str) -> str:
    """user:pass@host:port или полный URL → http://... с urlencoded user/pass."""
    u = (url or "").strip()
    if not u:
        return ""
    if "://" not in u:
        u = "http://" + u
    p = urlparse(u)
    if not p.hostname:
        return u
    user = quote(p.username or "", safe="")
    pwd = quote(p.password or "", safe="")
    auth = f"{user}:{pwd}@" if (user or pwd) else ""
    host = p.hostname
    port = f":{p.port}" if p.port else ""
    return urlunparse((p.scheme or "http", f"{auth}{host}{port}", "", "", "", ""))


def _resolve_proxy_url(explicit: str | None, use_proxy: bool) -> str:
    if not use_proxy:
        return ""
    if explicit:
        return _normalize_proxy(explicit)
    try:
        from .proxy_pool import current_proxy, proxy_enabled

        if proxy_enabled():
            return current_proxy() or ""
    except Exception:
        pass
    try:
        from config import ENRICH_PROXY

        return _normalize_proxy((ENRICH_PROXY or "").strip())
    except Exception:
        import os

        return _normalize_proxy(os.getenv("ENRICH_PROXY", "").strip())


def proxy_dict(proxy_url: str | None = None) -> dict[str, str] | None:
    """Текущий прокси (пул / ENRICH_PROXY). None — прокси не используется."""
    try:
        from .proxy_pool import proxy_enabled

        configured = proxy_enabled()
    except Exception:
        configured = False
    if proxy_url is None and not configured:
        try:
            from config import ENRICH_PROXY

            if not (ENRICH_PROXY or "").strip():
                return None
        except Exception:
            return None
    raw = _normalize_proxy(proxy_url) if proxy_url else _resolve_proxy_url(None, True)
    if not raw:
        return None
    return {"http": raw, "https": raw}


def make_session(
    base_headers: dict[str, str] | None = None,
    *,
    use_proxy: bool = False,
    proxy_url: str | None = None,
):
    """curl_cffi (Chrome) → httpx → requests.

    use_proxy=True — только для Companium/Checko.
    proxy_url — конкретный http://ip:port (из пула).
    """
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
        "X-Requested-With": "XMLHttpRequest",
    }
    if base_headers:
        headers.update(base_headers)

    raw = _resolve_proxy_url(proxy_url, use_proxy) if use_proxy else ""
    proxies = {"http": raw, "https": raw} if raw else None

    try:
        from curl_cffi import requests as crequests  # type: ignore

        s = crequests.Session()
        s.headers.update(headers)
        s._engine = "curl_cffi"  # type: ignore[attr-defined]
        s._impersonate = "chrome124"  # type: ignore[attr-defined]
        if proxies:
            s.proxies = proxies  # type: ignore[attr-defined]
        s._proxy_url = raw  # type: ignore[attr-defined]
        return s
    except Exception:
        pass

    try:
        import httpx

        class _HttpxWrap:
            _engine = "httpx"

            def __init__(self) -> None:
                kwargs: dict[str, Any] = {
                    "headers": headers,
                    "timeout": 45,
                    "follow_redirects": True,
                }
                if proxies:
                    kwargs["proxy"] = proxies.get("https") or proxies.get("http")
                self._c = httpx.Client(**kwargs)
                self._proxy_url = raw

            def get(self, url: str, **kwargs: Any):
                return self._c.get(url, **kwargs)

            def post(self, url: str, **kwargs: Any):
                return self._c.post(url, **kwargs)

        return _HttpxWrap()
    except Exception:
        import requests

        s = requests.Session()
        s.headers.update(headers)
        s._engine = "requests"  # type: ignore[attr-defined]
        if proxies:
            s.proxies.update(proxies)
        s._proxy_url = raw  # type: ignore[attr-defined]
        return s


def http_get(
    session,
    url: str,
    *,
    params: dict | None = None,
    timeout: int = 45,
    allow_redirects: bool = True,
):
    kwargs: dict[str, Any] = {"timeout": timeout}
    if params:
        kwargs["params"] = params
    engine = getattr(session, "_engine", "")
    if engine == "curl_cffi":
        kwargs["impersonate"] = getattr(session, "_impersonate", "chrome124")
        kwargs["allow_redirects"] = allow_redirects
    elif engine == "httpx":
        kwargs["follow_redirects"] = allow_redirects
    else:
        kwargs["allow_redirects"] = allow_redirects
    return session.get(url, **kwargs)


def session_proxy_url(session) -> str:
    return str(getattr(session, "_proxy_url", "") or "")
