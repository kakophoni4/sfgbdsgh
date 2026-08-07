"""
ФССП / исполнительные производства → колонка L.

Официальный API ФССП отключён; сайт часто с капчей.
Пробуем публичные эндпоинты; если нельзя — ПРОВЕРИТЬ + ссылка.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any
from urllib.parse import quote

from .http_util import http_get, make_session


@dataclass
class FsspReport:
    inn: str = ""
    proceedings: int | None = None
    error: str = ""
    source: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def fetch_fssp(inn: str) -> FsspReport:
    inn = (inn or "").strip()
    if not inn.isdigit() or len(inn) not in (10, 12):
        return FsspReport(inn=inn, error="bad_inn")

    session = make_session(
        {
            "Accept": "application/json, text/html, */*",
            "Referer": "https://fssp.gov.ru/",
        }
    )

    # Попытки «лёгких» точек (на разных серверах поведение разное)
    candidates = [
        f"https://fssp.gov.ru/iss/ip/?is%5Bvariant%5D=3&is%5Bregion_id%5D%5B0%5D=-1&is%5Blast_name%5D=&is%5Bfirst_name%5D=&is%5Bpatronymic%5D=&is%5Bdate%5D=&is%5Baddress%5D=&is%5Binn%5D={inn}",
        f"https://is-go.fssp.gov.ru/",
    ]

    last_err = "captcha_or_blocked"
    for url in candidates:
        try:
            r = http_get(session, url, allow_redirects=True, timeout=25)
            code = getattr(r, "status_code", 0)
            text = (r.text if hasattr(r, "text") else "") or ""
            if code >= 400:
                last_err = f"http_{code}"
                continue
            low = text.lower()
            if "captcha" in low or "капч" in low:
                last_err = "captcha"
                continue
            # эвристика по HTML (если когда-то отдаст список)
            if "исполнительн" in low and ("не найден" in low or "отсутствуют" in low):
                return FsspReport(inn=inn, proceedings=0, source=url)
            if "исполнительн" in low and ("результат" in low or "производств" in low):
                # не уверены в числе
                return FsspReport(inn=inn, proceedings=None, error="parse_uncertain", source=url)
            last_err = "no_signal"
        except Exception as e:  # noqa: BLE001
            last_err = str(e)

    return FsspReport(inn=inn, error=last_err)


def checklist_from_fssp(report: FsspReport) -> dict[str, Any]:
    link = (
        "https://fssp.gov.ru/iss/ip/"
        f"?is%5Bvariant%5D=3&is%5Binn%5D={quote(report.inn)}"
    )
    if report.error == "bad_inn":
        return {"L_debts_il": "", "L_note": "нет ИНН", "L_link": link}
    if report.proceedings == 0:
        return {
            "L_debts_il": "нет долгов/ИЛ",
            "L_note": "ФССП: производств не найдено",
            "L_link": link,
        }
    if report.proceedings and report.proceedings > 0:
        return {
            "L_debts_il": "есть долги/ИЛ",
            "L_note": f"ФССП: найдено производств ≈{report.proceedings}",
            "L_link": link,
        }
    return {
        "L_debts_il": "ПРОВЕРИТЬ",
        "L_note": f"ФССП авто недоступен ({report.error or 'unknown'}) — вручную",
        "L_link": link,
    }
