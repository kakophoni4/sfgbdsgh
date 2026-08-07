"""
Companium.ru → колонки P (суды), L (ФССП), I (недостоверки), доп. к V.

Карточка: https://companium.ru/id/{ogrn}
Нужен ОГРН (из ЕГРЮЛ). При капче — Playwright + клик по checkbox.

Сайт постепенно сворачивают в пользу checko.ru — пока страницы отдают данные, используем.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any

from .http_util import http_get, make_session

BASE = "https://companium.ru"


@dataclass
class CompaniumReport:
    inn: str = ""
    ogrn: str = ""
    url: str = ""
    court_cases: int | None = None
    enforcements: int | None = None
    unreliable: bool | None = None
    fedresurs_msgs: int | None = None
    name: str = ""
    error: str = ""
    source: str = "http"
    # доп. поля с карточки (не колонки A–X)
    employees: int | None = None
    capital_rub: int | None = None
    revenue_note: str = ""
    profit_note: str = ""
    taxes_rub: int | None = None
    insurance_rub: int | None = None
    msp: str = ""
    sanctions: str = ""
    licenses: str = ""
    bankruptcy_reg: str = ""
    checks: str = ""
    founder: str = ""
    extras: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _strip_html(html: str) -> str:
    t = re.sub(r"<script[\s\S]*?</script>", " ", html, flags=re.I)
    t = re.sub(r"<style[\s\S]*?</style>", " ", t, flags=re.I)
    t = re.sub(r"<[^>]+>", " ", t)
    return re.sub(r"\s+", " ", t)


def _has_captcha(html: str) -> bool:
    """Companium anti-bot: Google reCAPTCHA v2 + форма /check/humaneness."""
    low = html.lower()
    return any(
        x in low
        for x in (
            "g-recaptcha",
            "recaptcha.net",
            "check/humaneness",
            "подтвердите, что вы человек",
            "smartcaptcha",
            "я не робот",
        )
    )


def _parse_main(html: str, report: CompaniumReport) -> None:
    low = html.lower()
    if "нет записи о недостоверности" in low:
        report.unreliable = False
    elif "запись о недостоверности" in low or "сведения недостоверны" in low:
        report.unreliable = True

    m = re.search(
        r"Арбитражные дела\s*<span class=\"count\">(\d+)</span>",
        html,
    )
    if m:
        report.court_cases = int(m.group(1))
    m = re.search(
        r"Исполнительные про[^<]*<span class=\"count\">(\d+)</span>",
        html,
        re.I,
    )
    if m:
        report.enforcements = int(m.group(1))

    m = re.search(
        r"были рассмотрены\s*<a[^>]*>\s*([\d\s]+)\s*арбитражн",
        low,
    )
    if m and report.court_cases is None:
        report.court_cases = int(re.sub(r"\s+", "", m.group(1)))

    m = re.search(
        r"открыто\s*<a[^>]*>\s*([\d\s]+)\s*исполнительн",
        low,
    )
    if m and report.enforcements is None:
        report.enforcements = int(re.sub(r"\s+", "", m.group(1)))

    title = re.search(r"<title>([^<]+)", html)
    if title:
        report.name = title.group(1).split("–")[0].strip()


def _parse_legal(html: str, report: CompaniumReport) -> None:
    text = _strip_html(html).lower()
    if "нет сведений о судебных делах" in text or "нет сведений о судебн" in text:
        report.court_cases = 0
        return
    m = re.search(r"рассмотрены\s+([\d\s]+)\s+арбитражн", text)
    if m:
        report.court_cases = int(re.sub(r"\s+", "", m.group(1)))
        return
    m = re.search(r"([\d\s]{1,12})\s+арбитражн\w*\s+дел", text)
    if m:
        report.court_cases = int(re.sub(r"\s+", "", m.group(1)))


def _parse_enf(html: str, report: CompaniumReport) -> None:
    text = _strip_html(html).lower()
    if "не найдено ни одного" in text and "исполнительн" in text:
        report.enforcements = 0
        return
    m = re.search(r"открыто\s+([\d\s]+)\s+исполнительн", text)
    if m:
        report.enforcements = int(re.sub(r"\s+", "", m.group(1)))
        return
    m = re.search(r"([\d\s]{1,12})\s+исполнительн\w*\s+производств", text)
    if m:
        report.enforcements = int(re.sub(r"\s+", "", m.group(1)))


def _parse_fed(html: str, report: CompaniumReport) -> None:
    text = _strip_html(html).lower()
    if "не опубликовала и не является участником ни одно" in text:
        report.fedresurs_msgs = 0
        return
    if "ни одного сообщения" in text or "сообщений не найдено" in text:
        report.fedresurs_msgs = 0
        return
    m = re.search(r"([\d\s]{1,10})\s+сообщен", text)
    if m:
        report.fedresurs_msgs = int(re.sub(r"\s+", "", m.group(1)))


def _money_to_rub(raw: str) -> int | None:
    s = (raw or "").replace("\xa0", " ").strip().lower()
    if not s:
        return None
    mult = 1
    if "млрд" in s:
        mult = 1_000_000_000
    elif "млн" in s:
        mult = 1_000_000
    elif "тыс" in s:
        mult = 1_000
    digits = re.sub(r"[^\d]", "", s.split("=")[-1] if "=" in s else s)
    if not digits:
        return None
    try:
        n = int(digits)
    except ValueError:
        return None
    # если уже есть полное число после "=" (10 000) — не умножаем повторно
    if "=" in (raw or "") and re.search(r"=\s*[\d\s]{3,}", raw or ""):
        return n
    if mult > 1 and n < mult:
        return n * mult
    return n


def _parse_extras(html: str, report: CompaniumReport) -> None:
    """Сотрудники, капитал, налоги, МСП, санкции и т.п. с главной карточки."""
    text = _strip_html(html).replace("&nbsp;", " ").replace("&quot;", '"')
    text = re.sub(r"\s+", " ", text)

    m = re.search(
        r"среднесписочная численность работников за\s+(\d{4})\s+год составляет\s+(\d+)",
        text,
        re.I,
    )
    if m:
        report.employees = int(m.group(2))
        report.extras["employees_year"] = m.group(1)
    else:
        m = re.search(r"Сотрудники\s+Сотрудники\s+(\d+)\b", text)
        if m:
            report.employees = int(m.group(1))

    m = re.search(r"Уставный капитал\s+([^.]{3,60})", text)
    if m:
        report.capital_rub = _money_to_rub(m.group(1))
        report.extras["capital_raw"] = m.group(1).strip()[:80]

    m = re.search(
        r"Финансовая отчетность за\s+(\d{4})\s+год\s+(.*?)(?:Налоги и сборы|Управляющая)",
        text,
        re.I,
    )
    if m:
        report.extras["finance_year"] = m.group(1)
        blob = m.group(2)
        if "нет сведений о выручке" in blob.lower():
            report.revenue_note = "нет сведений"
        else:
            rm = re.search(r"выручк\w*\s+([\d\s.,]+(?:тыс|млн|млрд)?[^\s.]*)", blob, re.I)
            report.revenue_note = rm.group(1).strip() if rm else blob[:80].strip()
        if "нет сведений о чистой прибыли" in blob.lower():
            report.profit_note = "нет сведений"
        else:
            pm = re.search(r"прибыл\w*\s+([\d\s.,]+(?:тыс|млн|млрд)?[^\s.]*)", blob, re.I)
            report.profit_note = pm.group(1).strip() if pm else ""

    m = re.search(
        r"Уплачены налоги на сумму\s+([\d\s]+)\s*руб",
        text,
        re.I,
    )
    if m:
        report.taxes_rub = int(re.sub(r"\s+", "", m.group(1)))
    m = re.search(
        r"Уплачены страховые взносы на сумму\s+([\d\s]+)\s*руб",
        text,
        re.I,
    )
    if m:
        report.insurance_rub = int(re.sub(r"\s+", "", m.group(1)))

    m = re.search(r"Категория субъекта МСП:\s*([а-яё\-]+)", text, re.I)
    if m:
        report.msp = m.group(1).strip().lower()
    elif re.search(r"Входит в реестр.*МСП|единый реестр субъектов малого", text, re.I):
        report.msp = "в реестре МСП"

    if re.search(r"Не входит в санкционные списки", text, re.I):
        report.sanctions = "не входит"
    elif re.search(r"входит в санкцион", text, re.I):
        report.sanctions = "есть в санкционных списках"

    if re.search(r"Реестр банкротств\s+Нет сообщений о банкротстве", text, re.I):
        report.bankruptcy_reg = "нет сообщений"
    elif re.search(r"Реестр банкротств", text, re.I):
        report.bankruptcy_reg = "есть сообщения — проверить"

    if re.search(r"Нет сведений о (полученных |действующих )?лицензи", text, re.I):
        report.licenses = "нет сведений"
    elif re.search(r"Лицензии", text):
        report.licenses = "есть упоминание — проверить"

    if re.search(r"Нет сведений о проверках", text, re.I):
        report.checks = "нет сведений о проверках"
    elif re.search(r"Проверки и КНМ", text):
        report.checks = "есть данные о проверках — смотреть карточку"

    m = re.search(
        r"Учредитель\s+((?:ОБЩЕСТВО|АКЦИОНЕРНОЕ|ПУБЛИЧНОЕ|ИП|[А-ЯЁ][А-ЯЁ\s\"«»\-\.]{5,80}?))"
        r"(?:\s+с\s+\d|\s+Налоговый)",
        text,
    )
    if m:
        report.founder = re.sub(r"\s+", " ", m.group(1)).strip()[:120]


def human_dossier(report: CompaniumReport) -> str:
    """Короткая сводка для Excel/логов — без букв колонок."""
    parts: list[str] = []
    if report.error and report.court_cases is None and report.enforcements is None:
        return f"Companium недоступен: {report.error}"

    if report.court_cases is not None:
        parts.append(
            "суды: нет дел" if report.court_cases == 0 else f"суды: {report.court_cases} дел"
        )
    if report.enforcements is not None:
        parts.append(
            "долги ФССП: нет"
            if report.enforcements == 0
            else f"долги ФССП: {report.enforcements} пр."
        )
    if report.unreliable is False:
        parts.append("недостоверки: нет")
    elif report.unreliable is True:
        parts.append("недостоверки: ЕСТЬ")
    if report.fedresurs_msgs == 0:
        parts.append("федресурс: пусто")
    elif report.fedresurs_msgs:
        parts.append(f"федресурс: {report.fedresurs_msgs} сообщ.")
    if report.employees is not None:
        parts.append(f"сотрудники: {report.employees}")
    if report.msp:
        parts.append(f"МСП: {report.msp}")
    if report.capital_rub is not None:
        parts.append(f"уст.капитал: {report.capital_rub:,} ₽".replace(",", " "))
    if report.revenue_note:
        parts.append(f"выручка: {report.revenue_note}")
    if report.taxes_rub is not None:
        parts.append(f"налоги: {report.taxes_rub:,} ₽".replace(",", " "))
    if report.sanctions:
        parts.append(f"санкции: {report.sanctions}")
    if report.bankruptcy_reg:
        parts.append(f"банкротство: {report.bankruptcy_reg}")
    if report.licenses:
        parts.append(f"лицензии: {report.licenses}")
    if report.checks:
        parts.append(report.checks)
    if report.founder:
        parts.append(f"учредитель: {report.founder}")
    return "; ".join(parts) if parts else "данных мало"


def _fetch_http(ogrn: str) -> tuple[dict[str, str], str]:
    """Returns {page_name: html} and error."""
    session = make_session(
        {
            "Accept": "text/html,application/xhtml+xml",
            "Referer": f"{BASE}/",
        }
    )
    pages: dict[str, str] = {}
    main_url = f"{BASE}/id/{ogrn}"
    r = http_get(session, main_url, timeout=35)
    code = getattr(r, "status_code", 0)
    html = r.text if hasattr(r, "text") else ""
    if code == 404:
        return {}, "not_found"
    if code == 429 or _has_captcha(html):
        return {"main": html or ""}, "recaptcha_v2"
    if code >= 400:
        return {}, f"http_{code}"
    pages["main"] = html or ""
    for tab in ("legal-cases", "enforcements", "fedresurs"):
        try:
            rr = http_get(session, f"{BASE}/id/{ogrn}/{tab}", timeout=35)
            if getattr(rr, "status_code", 0) == 200:
                pages[tab] = rr.text or ""
        except Exception as e:  # noqa: BLE001
            pages[tab] = ""
            pages[f"{tab}_err"] = str(e)
    return pages, ""


def _fetch_playwright(ogrn: str) -> tuple[dict[str, str], str]:
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        return {}, "playwright_not_installed"

    pages: dict[str, str] = {}
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=["--disable-blink-features=AutomationControlled"],
            )
            context = browser.new_context(locale="ru-RU")
            page = context.new_page()
            url = f"{BASE}/id/{ogrn}"
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(1500)

            # Google reCAPTCHA v2: клик по checkbox; если bframe — картинки, не решаем
            html = page.content()
            if _has_captcha(html) or "человек" in page.title().lower():
                try:
                    page.wait_for_selector(
                        "iframe[src*='recaptcha'][src*='anchor']", timeout=12000
                    )
                    page.frame_locator(
                        "iframe[src*='recaptcha'][src*='anchor']"
                    ).locator("#recaptcha-anchor").click(timeout=8000)
                    page.wait_for_timeout(4000)
                except Exception:
                    pass

                # image challenge?
                if any("bframe" in (f.url or "") for f in page.frames):
                    browser.close()
                    return {"main": page.content()}, "recaptcha_image_challenge"

                checked = False
                for fr in page.frames:
                    if "anchor" in (fr.url or ""):
                        try:
                            checked = (
                                fr.get_attribute("#recaptcha-anchor", "aria-checked")
                                == "true"
                            )
                        except Exception:
                            pass
                if checked:
                    try:
                        page.locator("button[type=submit]").click(
                            timeout=5000, force=True
                        )
                        page.wait_for_timeout(3000)
                    except Exception:
                        pass
                else:
                    browser.close()
                    return {"main": page.content()}, "recaptcha_v2_unsolved"

            pages["main"] = page.content()
            if _has_captcha(pages["main"]) and "недостоверн" not in pages["main"].lower():
                browser.close()
                return pages, "recaptcha_v2"

            for tab in ("legal-cases", "enforcements", "fedresurs"):
                page.goto(
                    f"{BASE}/id/{ogrn}/{tab}",
                    wait_until="domcontentloaded",
                    timeout=60000,
                )
                page.wait_for_timeout(1200)
                pages[tab] = page.content()
            browser.close()
        return pages, ""
    except Exception as e:  # noqa: BLE001
        msg = str(e)
        if "Executable doesn't exist" in msg:
            return {}, "playwright_browser_missing"
        return {}, f"browser_{msg}"


def fetch_companium(*, ogrn: str = "", inn: str = "") -> CompaniumReport:
    ogrn = (ogrn or "").strip()
    inn = (inn or "").strip()
    if not ogrn.isdigit() or len(ogrn) not in (13, 15):
        return CompaniumReport(inn=inn, ogrn=ogrn, error="bad_ogrn")

    report = CompaniumReport(
        inn=inn,
        ogrn=ogrn,
        url=f"{BASE}/id/{ogrn}",
    )

    pages, err = _fetch_http(ogrn)
    report.source = "http"
    if err in {"recaptcha_v2", "captcha"} or (err == "" and not pages.get("main")):
        pages, err = _fetch_playwright(ogrn)
        report.source = "playwright"

    if err and err.startswith("recaptcha"):
        report.error = err
        return report
    if err and not pages.get("main"):
        report.error = err
        return report

    main = pages.get("main") or ""
    if "не найдена" in main.lower() and "404" in main:
        report.error = "not_found"
        return report

    _parse_main(main, report)
    _parse_extras(main, report)
    if "legal-cases" in pages:
        _parse_legal(pages["legal-cases"], report)
    if "enforcements" in pages:
        _parse_enf(pages["enforcements"], report)
    if "fedresurs" in pages:
        _parse_fed(pages["fedresurs"], report)

    if (
        report.court_cases is None
        and report.enforcements is None
        and report.unreliable is None
    ):
        report.error = report.error or "parse_empty"
    return report


def checklist_from_companium(report: CompaniumReport) -> dict[str, Any]:
    link = report.url or f"{BASE}/id/{report.ogrn}"
    out: dict[str, Any] = {
        "P_link": f"{link}/legal-cases",
        "L_link": f"{link}/enforcements",
        "I_note": "",
        "companium_url": link,
        "dossier": human_dossier(report),
    }

    if report.error and report.court_cases is None and report.enforcements is None:
        out.update(
            {
                "P_court_cases": "ПРОВЕРИТЬ",
                "P_note": f"Companium: {report.error}",
                "L_debts_il": "ПРОВЕРИТЬ",
                "L_note": f"Companium: {report.error}",
            }
        )
        if report.unreliable is None:
            out["I_reliable"] = "ПРОВЕРИТЬ"
            out["I_note"] = f"Companium: {report.error}"
        return out

    if report.court_cases is None:
        out["P_court_cases"] = "ПРОВЕРИТЬ"
        out["P_note"] = "Companium: число дел не разобрано"
    else:
        n = report.court_cases
        out["P_court_cases"] = "есть дела" if n > 0 else "нет дел"
        out["P_note"] = f"Companium: дел={n}"

    if report.enforcements is None:
        out["L_debts_il"] = "ПРОВЕРИТЬ"
        out["L_note"] = "Companium: ФССП не разобрано"
    else:
        n = report.enforcements
        out["L_debts_il"] = "есть долги/ИЛ" if n > 0 else "нет долгов/ИЛ"
        out["L_note"] = f"Companium: производств={n}"

    if report.unreliable is True:
        out["I_reliable"] = "НЕТ"
        out["I_note"] = "Companium: есть недостоверность сведений"
    elif report.unreliable is False:
        out["I_reliable"] = "ДА"
        out["I_note"] = "Companium: нет записи о недостоверности"
    else:
        out["I_reliable"] = "ПРОВЕРИТЬ"
        out["I_note"] = "Companium: недостоверность не определена"

    if report.fedresurs_msgs is not None:
        if report.fedresurs_msgs == 0:
            out["V_leases"] = "нет лизинга/залогов"
            out["V_note"] = "Companium/Федресурс: сообщений нет"
        else:
            out["V_leases"] = "ПРОВЕРИТЬ"
            out["V_note"] = f"Companium/Федресурс: сообщений≈{report.fedresurs_msgs}"

    # доп. поля для Excel (человекочитаемые)
    if report.employees is not None:
        out["employees"] = report.employees
    if report.msp:
        out["msp"] = report.msp
    if report.sanctions:
        out["sanctions"] = report.sanctions
    if report.capital_rub is not None:
        out["capital_rub"] = report.capital_rub
    if report.taxes_rub is not None:
        out["taxes_rub"] = report.taxes_rub
    if report.insurance_rub is not None:
        out["insurance_rub"] = report.insurance_rub
    if report.revenue_note:
        out["revenue_note"] = report.revenue_note
    if report.licenses:
        out["licenses"] = report.licenses
    if report.checks:
        out["checks"] = report.checks
    if report.founder:
        out["founder"] = report.founder
    if report.bankruptcy_reg:
        out["bankruptcy_reg"] = report.bankruptcy_reg

    return out
