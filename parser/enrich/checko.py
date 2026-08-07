"""
Checko.ru — запасной источник P/L/I/V (наследник Companium).

Карточка: https://checko.ru/company/{ogrn}
Основная страница часто уже содержит блоки судов/ФССП (отдельные вкладки чаще капчат).
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any

from .http_util import http_get, make_session, session_proxy_url
from .proxy_pool import (
    current_proxy,
    is_proxy_dead_error,
    mark_bad,
    max_tries,
    proxy_enabled,
    rotate_proxy,
)

BASE = "https://checko.ru"


@dataclass
class CheckoReport:
    inn: str = ""
    ogrn: str = ""
    url: str = ""
    court_cases: int | None = None
    enforcements: int | None = None
    unreliable: bool | None = None
    fedresurs_empty: bool | None = None
    name: str = ""
    error: str = ""
    source: str = "http"
    extras: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _strip(html: str) -> str:
    t = re.sub(r"<script[\s\S]*?</script>", " ", html, flags=re.I)
    t = re.sub(r"<style[\s\S]*?</style>", " ", t, flags=re.I)
    t = re.sub(r"<[^>]+>", " ", t)
    return re.sub(r"\s+", " ", t)


def _parse(html: str, report: CheckoReport) -> None:
    text = _strip(html)
    low = text.lower()

    title = re.search(r"<title>([^<]+)", html)
    if title:
        report.name = title.group(1).split("-")[0].strip()

    # I
    if "нет записи о недостоверности" in low or "недостоверные сведения отсутствуют" in low:
        report.unreliable = False
    elif "недостоверные сведения" in low or "сведения недостоверны" in low:
        report.unreliable = True

    # P
    if re.search(r"арбитражн\w*\s+дел\w*.{0,40}не найдено ни одного", low):
        report.court_cases = 0
    elif "не найдено ни одного дела" in low and "арбитраж" in low:
        report.court_cases = 0
    else:
        m = re.search(
            r"арбитражн\w*\s+дел\w*.{0,40}?(\d[\d\s]{0,12}\d|\d+)\s*(дел|арбитраж)",
            low,
        )
        if m:
            report.court_cases = int(re.sub(r"\s+", "", m.group(1)))
        else:
            m = re.search(r"найден[оа]\s+(\d[\d\s]*)\s+арбитражн", low)
            if m:
                report.court_cases = int(re.sub(r"\s+", "", m.group(1)))

    # L
    if re.search(
        r"нет сведений об открытых.{0,80}исполнительн",
        low,
    ) or re.search(r"исполнительн\w*\s+производств\w*.{0,40}не найден", low):
        report.enforcements = 0
    else:
        m = re.search(
            r"открыто\s+(\d[\d\s]*)\s+исполнительн",
            low,
        )
        if m:
            report.enforcements = int(re.sub(r"\s+", "", m.group(1)))
        else:
            m = re.search(r"(\d[\d\s]*)\s+исполнительн\w*\s+производств", low)
            if m:
                report.enforcements = int(re.sub(r"\s+", "", m.group(1)))

    # V soft
    if re.search(
        r"федресурс.{0,80}(не опубликован|не является участником|сообщений нет|не найдено)",
        low,
    ):
        report.fedresurs_empty = True
    elif "федресурс" in low and re.search(r"(\d+)\s+сообщен", low):
        report.fedresurs_empty = False


def fetch_checko(*, ogrn: str = "", inn: str = "") -> CheckoReport:
    ogrn = (ogrn or "").strip()
    inn = (inn or "").strip()
    if not ogrn.isdigit() or len(ogrn) not in (13, 15):
        return CheckoReport(inn=inn, ogrn=ogrn, error="bad_ogrn")

    url = f"{BASE}/company/{ogrn}"
    report = CheckoReport(inn=inn, ogrn=ogrn, url=url)
    tries = max_tries() if proxy_enabled() else 1
    last_err = "proxy_exhausted"
    for _attempt in range(tries):
        proxy = current_proxy() if proxy_enabled() else None
        session = make_session(
            {
                "Accept": "text/html,application/xhtml+xml",
                "Referer": f"{BASE}/",
            },
            use_proxy=bool(proxy) or proxy_enabled(),
            proxy_url=proxy,
        )
        try:
            r = http_get(session, url, timeout=35)
        except Exception as e:  # noqa: BLE001
            if proxy_enabled() and is_proxy_dead_error(e):
                mark_bad(proxy or session_proxy_url(session), reason=str(e))
                rotate_proxy()
                last_err = str(e)
                continue
            report.error = str(e)
            return report

        code = getattr(r, "status_code", 0)
        html = r.text if hasattr(r, "text") else ""
        used = session_proxy_url(session) or proxy
        if code == 429 or "captcha_required" in (html or "").lower():
            if proxy_enabled():
                mark_bad(used, reason="captcha_429")
                rotate_proxy()
                last_err = "captcha_429"
                continue
            report.error = "captcha_429"
            return report
        if code == 404:
            report.error = "not_found"
            return report
        if code >= 400:
            if proxy_enabled():
                mark_bad(used, reason=f"http_{code}")
                rotate_proxy()
                last_err = f"http_{code}"
                continue
            report.error = f"http_{code}"
            return report
        if "подтвердите, что вы человек" in (html or "").lower() or "g-recaptcha" in (
            html or ""
        ).lower():
            if proxy_enabled():
                mark_bad(used, reason="recaptcha_v2")
                rotate_proxy()
                last_err = "recaptcha_v2"
                continue
            report.error = "recaptcha_v2"
            return report
        _parse(html or "", report)
        if (
            report.court_cases is None
            and report.enforcements is None
            and report.unreliable is None
        ):
            report.error = "parse_empty"
        return report
    report.error = last_err
    return report


def checklist_from_checko(report: CheckoReport) -> dict[str, Any]:
    """Только заполненные поля — чтобы не затирать удачные значения других источников."""
    out: dict[str, Any] = {"checko_url": report.url or f"{BASE}/company/{report.ogrn}"}
    if report.error and report.court_cases is None and report.enforcements is None:
        out["checko_error"] = report.error
        return out

    if report.court_cases is not None:
        n = report.court_cases
        out["P_court_cases"] = "есть дела" if n > 0 else "нет дел"
        out["P_note"] = f"Checko: дел={n}"
        out["P_link"] = f"{report.url}/legal-cases"

    if report.enforcements is not None:
        n = report.enforcements
        out["L_debts_il"] = "есть долги/ИЛ" if n > 0 else "нет долгов/ИЛ"
        out["L_note"] = f"Checko: производств={n}"
        out["L_link"] = f"{report.url}/enforcements"

    if report.unreliable is True:
        out["I_reliable"] = "НЕТ"
        out["I_note"] = "Checko: есть недостоверность"
    elif report.unreliable is False:
        out["I_reliable"] = "ДА"
        out["I_note"] = "Checko: недостоверности не видно"

    if report.fedresurs_empty is True:
        out["V_leases"] = "нет лизинга/залогов"
        out["V_note"] = "Checko/Федресурс: пусто"
    elif report.fedresurs_empty is False:
        out["V_leases"] = "ПРОВЕРИТЬ"
        out["V_note"] = "Checko/Федресурс: есть сообщения"

    return out
