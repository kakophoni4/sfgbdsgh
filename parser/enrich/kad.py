"""Арбитражные дела (КАД) → колонка P: ЕСТЬ / НЕТ / ПРОВЕРИТЬ.

Сначала HTTP; при 451 — Playwright (если установлен).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from .http_util import make_session

SEARCH_URLS = (
    "https://kad.arbitr.ru/Kad/SearchInstances",
    "https://m.kad.arbitr.ru/Kad/SearchInstances",
)


@dataclass
class KadReport:
    inn: str = ""
    cases_found: int | None = None
    sample: list[str] | None = None
    error: str = ""
    source: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _fetch_kad_http(inn: str) -> KadReport:
    payload = {
        "Page": 1,
        "Count": 25,
        "Courts": [],
        "DateFrom": None,
        "DateTo": None,
        "Sides": [{"Name": inn, "Type": -1, "ExactMatch": False}],
        "Judges": [],
        "CaseNumbers": [],
        "WithVKSInstances": False,
    }
    headers = {
        "Content-Type": "application/json;charset=UTF-8",
        "Accept": "application/json, text/plain, */*",
        "X-Requested-With": "XMLHttpRequest",
        "Origin": "https://kad.arbitr.ru",
        "Referer": "https://kad.arbitr.ru/",
    }

    session = make_session(headers)
    last_err = ""
    for url in SEARCH_URLS:
        try:
            home = url.split("/Kad/")[0] + "/"
            engine = getattr(session, "_engine", "")
            try:
                if engine == "curl_cffi":
                    session.get(
                        home,
                        timeout=20,
                        impersonate=getattr(session, "_impersonate", "chrome124"),
                    )
                else:
                    session.get(home, timeout=20)
            except Exception:
                pass

            if engine == "curl_cffi":
                r = session.post(
                    url,
                    json=payload,
                    timeout=40,
                    impersonate=getattr(session, "_impersonate", "chrome124"),
                )
            else:
                r = session.post(url, json=payload, timeout=40)

            code = getattr(r, "status_code", 0)
            text = r.text if hasattr(r, "text") else ""
            if code == 451 or "заблокирован" in text.lower():
                last_err = "blocked_451"
                continue
            if code >= 400:
                last_err = f"http_{code}"
                continue
            if text.lstrip()[:1] not in ("{", "["):
                last_err = "non_json"
                continue

            data = r.json()
            items = []
            if isinstance(data, dict):
                items = (
                    data.get("Result")
                    or data.get("items")
                    or data.get("Items")
                    or data.get("data")
                    or []
                )
                total = data.get("TotalCount") or data.get("totalCount") or data.get("Count")
            elif isinstance(data, list):
                items = data
                total = len(items)
            else:
                last_err = "bad_shape"
                continue

            if total is None:
                total = len(items) if isinstance(items, list) else 0

            samples: list[str] = []
            if isinstance(items, list):
                for it in items[:5]:
                    if isinstance(it, dict):
                        num = (
                            it.get("CaseNumber")
                            or it.get("caseNumber")
                            or it.get("Number")
                            or ""
                        )
                        if num:
                            samples.append(str(num))

            return KadReport(
                inn=inn,
                cases_found=int(total),
                sample=samples,
                source=url,
            )
        except Exception as e:  # noqa: BLE001
            last_err = str(e)
            continue

    return KadReport(inn=inn, error=last_err or "unreachable")


def fetch_kad(inn: str) -> KadReport:
    inn = (inn or "").strip()
    if not inn.isdigit():
        return KadReport(inn=inn, error="bad_inn")

    from .kad_browser import browser_mode, fetch_kad_browser, playwright_available

    mode = browser_mode()
    if mode == "always":
        return fetch_kad_browser(inn)
    if mode == "never":
        return _fetch_kad_http(inn)

    # auto
    http = _fetch_kad_http(inn)
    if not http.error:
        return http
    if http.error == "blocked_451" and playwright_available():
        browser = fetch_kad_browser(inn)
        # если браузер тоже не смог — вернём его ошибку (информативнее)
        return browser
    if http.error == "blocked_451" and not playwright_available():
        return KadReport(
            inn=inn,
            error="blocked_451_install_playwright",
            source=http.source,
        )
    return http


def checklist_from_kad(report: KadReport) -> dict[str, Any]:
    if report.error:
        return {
            "P_court_cases": "ПРОВЕРИТЬ",
            "P_note": f"КАД недоступен: {report.error}",
            "P_link": f"https://kad.arbitr.ru/?partner_inn={report.inn}",
        }
    n = report.cases_found or 0
    return {
        "P_court_cases": "ЕСТЬ" if n > 0 else "НЕТ",
        "P_note": f"дел={n}"
        + (f"; примеры: {', '.join(report.sample or [])}" if report.sample else ""),
        "P_link": "https://kad.arbitr.ru/",
        "P_source": report.source,
    }
