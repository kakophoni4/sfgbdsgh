from __future__ import annotations

from typing import Any
from urllib.parse import quote, urlparse, urlunparse


def _proxy_url() -> str:
    """Только ENRICH_PROXY — не подхватываем системный HTTP_PROXY на все сайты."""
    try:
        from config import ENRICH_PROXY

        return (ENRICH_PROXY or "").strip()
    except Exception:
        import os

        return os.getenv("ENRICH_PROXY", "").strip()


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


def proxy_dict() -> dict[str, str] | None:
    raw = _normalize_proxy(_proxy_url())
    if not raw:
        return None
    return {"http": raw, "https": raw}


def proxy_playwright() -> dict[str, str] | None:
    """Настройки прокси для Playwright (Companium browser fallback)."""
    raw = _proxy_url()
    if not raw:
        return None
    if "://" not in raw:
        raw = "http://" + raw
    p = urlparse(raw)
    if not p.hostname:
        return None
    server = f"{p.scheme or 'http'}://{p.hostname}" + (f":{p.port}" if p.port else "")
    out: dict[str, str] = {"server": server}
    if p.username:
        out["username"] = p.username
    if p.password:
        out["password"] = p.password
    return out


def make_session(
    base_headers: dict[str, str] | None = None,
    *,
    use_proxy: bool = False,
):
    """curl_cffi (Chrome) → httpx → requests.

    use_proxy=True — только для Companium/Checko (ENRICH_PROXY).
    Остальные источники ходят напрямую.
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

    proxies = proxy_dict() if use_proxy else None

    try:
        from curl_cffi import requests as crequests  # type: ignore

        s = crequests.Session()
        s.headers.update(headers)
        s._engine = "curl_cffi"  # type: ignore[attr-defined]
        s._impersonate = "chrome124"  # type: ignore[attr-defined]
        if proxies:
            s.proxies = proxies  # type: ignore[attr-defined]
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
