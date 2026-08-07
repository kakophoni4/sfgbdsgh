"""
Федресурс / ЕФРСБ → колонки O (банкротство) и V (лизинг/сообщения).

Публичный backend:
  GET https://fedresurs.ru/backend/companies?searchString={inn}
Статус с «банкрот» → риск по O.
Публикации/сообщения часто 451/капча → V = ПРОВЕРИТЬ + ссылка.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any
from urllib.parse import quote

from .http_util import http_get, make_session

BASE = "https://fedresurs.ru"
BANKRUPT_MARKERS = (
    "банкрот",
    "несостоятельн",
    "конкурсн",
    "наблюдени",
    "внешнее управление",
    "реализац",
)
LEASE_MARKERS = ("лизинг", "аренда финанс", "залог", "обременен")


@dataclass
class FedresursReport:
    inn: str = ""
    guid: str = ""
    name: str = ""
    status: str = ""
    is_bankrupt: bool | None = None
    lease_hits: int | None = None
    lease_note: str = ""
    error: str = ""
    source: str = ""
    extras: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _is_bankrupt_status(status: str) -> bool:
    s = (status or "").lower()
    return any(m in s for m in BANKRUPT_MARKERS)


def fetch_fedresurs(inn: str) -> FedresursReport:
    inn = (inn or "").strip()
    if not inn.isdigit() or len(inn) not in (10, 12):
        return FedresursReport(inn=inn, error="bad_inn")

    session = make_session(
        {
            "Accept": "application/json, text/plain, */*",
            "Origin": BASE,
            "Referer": f"{BASE}/",
        }
    )
    url = f"{BASE}/backend/companies?limit=15&offset=0&searchString={quote(inn)}"
    try:
        r = http_get(session, url, timeout=30)
        code = getattr(r, "status_code", 0)
        if code >= 400:
            return FedresursReport(inn=inn, error=f"http_{code}", source=url)
        data = r.json()
        rows = data.get("pageData") or []
        match = None
        for row in rows:
            if str(row.get("inn") or "") == inn:
                match = row
                break
        if match is None and rows:
            # точного ИНН нет — не подставляем чужую карточку
            return FedresursReport(
                inn=inn,
                error="not_found",
                source=url,
                extras={"found": data.get("found"), "sample_inns": [x.get("inn") for x in rows[:3]]},
            )
        if match is None:
            return FedresursReport(inn=inn, error="not_found", source=url, is_bankrupt=False)

        status = ""
        if isinstance(match.get("status"), dict):
            status = str(match["status"].get("name") or "")
        else:
            status = str(match.get("status") or "")

        guid = str(match.get("guid") or "")
        report = FedresursReport(
            inn=inn,
            guid=guid,
            name=str(match.get("name") or ""),
            status=status,
            is_bankrupt=_is_bankrupt_status(status),
            source=url,
        )

        # детальная карточка — уточняет статус
        if guid:
            try:
                d = http_get(session, f"{BASE}/backend/companies/{guid}", timeout=25)
                if getattr(d, "status_code", 0) == 200:
                    detail = d.json()
                    st = detail.get("status")
                    if isinstance(st, dict) and st.get("name"):
                        report.status = str(st["name"])
                        report.is_bankrupt = _is_bankrupt_status(report.status)
                    report.extras["detail_ok"] = True
            except Exception as e:  # noqa: BLE001
                report.extras["detail_err"] = str(e)

            # публикации (лизинг/залоги) — часто блокируются
            pub_url = f"{BASE}/backend/companies/{guid}/publications?limit=25&offset=0"
            try:
                p = http_get(session, pub_url, timeout=30)
                pcode = getattr(p, "status_code", 0)
                if pcode == 451:
                    report.lease_hits = None
                    report.lease_note = "publications_blocked_451"
                elif pcode >= 400:
                    report.lease_hits = None
                    report.lease_note = f"publications_http_{pcode}"
                else:
                    text = (p.text if hasattr(p, "text") else "") or ""
                    low = text.lower()
                    hits = sum(1 for m in LEASE_MARKERS if m in low)
                    # если JSON со списком — считаем по типам
                    try:
                        pj = p.json()
                        items = pj.get("pageData") or pj.get("items") or pj.get("Result") or []
                        if isinstance(items, list):
                            lease_n = 0
                            for it in items:
                                blob = str(it).lower()
                                if any(m in blob for m in LEASE_MARKERS):
                                    lease_n += 1
                            report.lease_hits = lease_n
                            report.lease_note = f"publications={len(items)}; lease_like={lease_n}"
                        else:
                            report.lease_hits = hits
                            report.lease_note = "publications_non_list"
                    except Exception:
                        report.lease_hits = hits if hits else 0
                        report.lease_note = "publications_text_scan"
            except Exception as e:  # noqa: BLE001
                report.lease_hits = None
                report.lease_note = str(e)

        return report
    except Exception as e:  # noqa: BLE001
        return FedresursReport(inn=inn, error=str(e), source=url)


def checklist_from_fedresurs(report: FedresursReport) -> dict[str, Any]:
    link = f"{BASE}/companies?searchString={quote(report.inn)}"
    if report.guid:
        link = f"{BASE}/companies/{report.guid}"

    out: dict[str, Any] = {
        "O_link": link,
        "V_link": link,
        "fedresurs_status": report.status,
    }

    if report.error == "bad_inn":
        out.update({"O_clean": "", "O_note": "нет ИНН", "V_leases": "", "V_note": "нет ИНН"})
        return out

    if report.error and report.is_bankrupt is None:
        out.update(
            {
                "O_clean": "ПРОВЕРИТЬ",
                "O_note": f"Федресурс: {report.error}",
                "V_leases": "ПРОВЕРИТЬ",
                "V_note": f"Федресурс: {report.error}",
            }
        )
        return out

    if report.is_bankrupt:
        out["O_clean"] = "есть банкротство"
        out["O_note"] = f"ЕФРСБ/Федресурс: {report.status or 'банкротство'}"
    else:
        out["O_clean"] = "нет банкротства"
        out["O_note"] = f"статус: {report.status or 'действующее'}"

    # 451/капча на /publications — НЕ ставим V=ПРОВЕРИТЬ (иначе затирает
    # «нет лизинга» с Companium/Checko). Только O + ссылка; V оставляем дырой
    # или уже заполненным агрегаторами.
    if report.lease_hits is None:
        out["V_note"] = report.lease_note or "публикации Федресурса недоступны (451)"
        # V_leases намеренно не трогаем
    elif report.lease_hits > 0:
        out["V_leases"] = "есть лизинг/залоги"
        out["V_note"] = report.lease_note
    else:
        out["V_leases"] = "нет лизинга/залогов"
        out["V_note"] = report.lease_note or "в публикациях не найдено"

    return out


def merge_o_disqualified(checklist: dict[str, Any], disc_note: str, found: bool | None) -> dict[str, Any]:
    """Дополнить O результатом проверки дисквалификации директора."""
    cl = dict(checklist)
    if found is True:
        if cl.get("O_clean") == "есть банкротство":
            cl["O_clean"] = "есть банкротство/дисквал"
        else:
            cl["O_clean"] = "есть дисквал"
        prev = cl.get("O_note") or ""
        cl["O_note"] = (prev + "; " if prev else "") + disc_note
    elif found is False:
        prev = cl.get("O_note") or ""
        if "дисквал" not in prev.lower():
            cl["O_note"] = (prev + "; " if prev else "") + "дисквал: не найден"
    else:
        prev = cl.get("O_note") or ""
        cl["O_note"] = (prev + "; " if prev else "") + disc_note
    return cl


_NAME_SPLIT = re.compile(r"\s+")


def fetch_disqualified(fio: str) -> tuple[bool | None, str]:
    """
    service.nalog.ru/disqualified — часто капча.
    Возвращает (found|None, note).
    """
    fio = (fio or "").strip()
    if len(fio) < 5:
        return None, "дисквал: нет ФИО"

    parts = _NAME_SPLIT.split(fio)
    # директор в ЕГРЮЛ часто: «ГЕНЕРАЛЬНЫЙ ДИРЕКТОР ИВАНОВ ИВАН ИВАНОВИЧ»
    # берём последние 3 слова как ФИО, если длиннее
    if len(parts) >= 3:
        # отрезать должности
        skip = {
            "генеральный",
            "директор",
            "управляющий",
            "руководитель",
            "президент",
            "председатель",
            "ликвидатор",
        }
        name_parts = [p for p in parts if p.lower().rstrip(".") not in skip]
        if len(name_parts) >= 3:
            parts = name_parts[-3:]
        elif len(name_parts) >= 2:
            parts = name_parts[-2:]

    last = parts[0] if parts else ""
    first = parts[1] if len(parts) > 1 else ""
    patronymic = parts[2] if len(parts) > 2 else ""

    session = make_session(
        {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Referer": "https://service.nalog.ru/disqualified.do",
        }
    )
    url = "https://service.nalog.ru/disqualified-search.do"
    try:
        # форма часто POST; пробуем GET-параметры как мягкий зонд
        r = http_get(
            session,
            url,
            params={
                "fam": last,
                "nam": first,
                "otch": patronymic,
                "region": "",
            },
            timeout=25,
        )
        code = getattr(r, "status_code", 0)
        text = (r.text if hasattr(r, "text") else "") or ""
        low = text.lower()
        if code >= 400:
            return None, f"дисквал: http_{code}"
        if "captcha" in low or "капч" in low:
            return None, "дисквал: капча"
        if "не найден" in low or "отсутствуют" in low or "нет сведений" in low:
            return False, f"дисквал: не найден ({last} {first})"
        if "дисквалифиц" in low and ("найден" in low or "<table" in low):
            return True, f"дисквал: возможно есть ({last} {first})"
        return None, "дисквал: ПРОВЕРИТЬ вручную"
    except Exception as e:  # noqa: BLE001
        return None, f"дисквал: {e}"
