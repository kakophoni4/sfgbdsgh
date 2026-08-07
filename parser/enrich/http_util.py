from __future__ import annotations

from typing import Any


def make_session(base_headers: dict[str, str] | None = None):
    """curl_cffi (Chrome) → httpx → requests."""
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

    try:
        from curl_cffi import requests as crequests  # type: ignore

        s = crequests.Session()
        s.headers.update(headers)
        s._engine = "curl_cffi"  # type: ignore[attr-defined]
        s._impersonate = "chrome124"  # type: ignore[attr-defined]
        return s
    except Exception:
        pass

    try:
        import httpx

        class _HttpxWrap:
            _engine = "httpx"

            def __init__(self) -> None:
                self._c = httpx.Client(
                    headers=headers, timeout=45, follow_redirects=True
                )

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
        # httpx client already configured; pass follow_redirects per-request if possible
        kwargs["follow_redirects"] = allow_redirects
    else:
        kwargs["allow_redirects"] = allow_redirects
    return session.get(url, **kwargs)
