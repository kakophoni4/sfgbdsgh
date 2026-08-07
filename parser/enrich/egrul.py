from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from typing import Any

BASE = "https://egrul.nalog.ru"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)


@dataclass
class EgrulRecord:
    name: str = ""
    name_full: str = ""
    inn: str = ""
    ogrn: str = ""
    kpp: str = ""
    address: str = ""
    director: str = ""
    status: str = ""
    reg_date: str = ""
    okved: str = ""
    kind: str = ""
    raw: dict[str, Any] | None = None
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _session():
    """Предпочитаем curl_cffi (Chrome TLS), иначе requests."""
    try:
        from curl_cffi import requests as crequests  # type: ignore

        s = crequests.Session()
        s.headers.update(
            {
                "User-Agent": UA,
                "Accept": "application/json, text/javascript, */*; q=0.01",
                "X-Requested-With": "XMLHttpRequest",
                "Referer": f"{BASE}/index.html",
            }
        )
        s._impersonate = "chrome124"  # type: ignore[attr-defined]
        s._engine = "curl_cffi"
        return s
    except Exception:
        import requests

        s = requests.Session()
        s.headers.update(
            {
                "User-Agent": UA,
                "Accept": "application/json, text/javascript, */*; q=0.01",
                "X-Requested-With": "XMLHttpRequest",
                "Referer": f"{BASE}/index.html",
            }
        )
        s._engine = "requests"  # type: ignore[attr-defined]
        return s


def _post(session, url: str, data: dict) -> dict:
    kwargs = {"data": data, "timeout": 30}
    if getattr(session, "_engine", "") == "curl_cffi":
        kwargs["impersonate"] = getattr(session, "_impersonate", "chrome124")
    r = session.post(url, **kwargs)
    r.raise_for_status()
    return r.json()


def _get(session, url: str) -> dict:
    kwargs = {"timeout": 30}
    if getattr(session, "_engine", "") == "curl_cffi":
        kwargs["impersonate"] = getattr(session, "_impersonate", "chrome124")
    r = session.get(url, **kwargs)
    r.raise_for_status()
    return r.json()


def _row_to_record(row: dict[str, Any]) -> EgrulRecord:
    status = (row.get("e") or row.get("cnt") or "").strip()
    if not status:
        status = "действующая"
    return EgrulRecord(
        name=(row.get("c") or row.get("n") or "").strip(),
        name_full=(row.get("n") or "").strip(),
        inn=(row.get("i") or "").strip(),
        ogrn=(row.get("o") or "").strip(),
        kpp=(row.get("p") or "").strip(),
        address=(row.get("a") or "").strip(),
        director=(row.get("g") or "").strip(),
        status=status,
        reg_date=(row.get("r") or "").strip(),
        okved=(row.get("okved") or row.get("ok") or "").strip(),
        kind=(row.get("k") or "").strip(),
        raw=row,
    )


def search_egrul(query: str, *, retries: int = 2) -> list[EgrulRecord]:
    query = (query or "").strip()
    if not query:
        return []

    last_err = ""
    for attempt in range(retries + 1):
        try:
            session = _session()
            token_resp = _post(
                session,
                f"{BASE}/",
                {
                    "query": query,
                    "vyp3CaptchaToken": "",
                    "page": "",
                    "region": "",
                    "PreventChromeAutocomplete": "",
                },
            )
            if token_resp.get("captchaRequired") or token_resp.get("captcha"):
                return [EgrulRecord(error="captcha")]
            token = token_resp.get("t")
            if not token:
                return [EgrulRecord(error=f"no_token:{json.dumps(token_resp, ensure_ascii=False)[:200]}")]

            rows: list[dict] = []
            for _ in range(15):
                res = _get(session, f"{BASE}/search-result/{token}")
                rows = res.get("rows") or []
                if rows:
                    break
                time.sleep(0.5)
            return [_row_to_record(r) for r in rows]
        except Exception as e:  # noqa: BLE001
            last_err = str(e)
            time.sleep(1.2 * (attempt + 1))
    return [EgrulRecord(error=last_err or "unknown")]


def lookup_company(
    *,
    inn: str = "",
    ogrn: str = "",
    name: str = "",
) -> EgrulRecord:
    for q, kind in ((inn, "inn"), (ogrn, "ogrn"), (name, "name")):
        q = (q or "").strip()
        if not q:
            continue
        rows = search_egrul(q)
        if not rows:
            continue
        if rows[0].error:
            return rows[0]
        if kind == "inn":
            for r in rows:
                if r.inn == q:
                    return r
        if kind == "ogrn":
            for r in rows:
                if r.ogrn == q:
                    return r
        return rows[0]
    return EgrulRecord(error="empty_query")


def status_flags(status: str) -> dict[str, str]:
    s = (status or "").lower()
    liquid_markers = ("ликвидац", "в процессе ликвидации", "ликвидиров")
    exclude_markers = ("исключ", "недействующ", "реорганизац")

    on_liquid = any(m in s for m in liquid_markers)
    on_exclude = any(m in s for m in exclude_markers)

    if not s or "действующ" in s:
        return {"M": "ДА", "N": "ДА", "status": status or "действующая"}

    return {
        "M": "НЕТ" if on_liquid else "ДА",
        "N": "НЕТ" if on_exclude else "ДА",
        "status": status,
    }
