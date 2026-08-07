"""Заливка в Google Sheets через Apps Script (без Google Cloud).

v3: листы по дням, только нормальные лоты, компактные колонки, цвета в скрипте.
"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from config import GOOGLE_APPS_SCRIPT_TOKEN, GOOGLE_APPS_SCRIPT_URL
from parser.export_excel import (
    _first_seen_day,
    _human_flag,
    _sheet_title,
    _zsk_cell,
)

EXPORT_VERSION = "v4-row-colors-score"

# Компактная шапка для онлайн-таблицы (без сырого текста и ручных пустышек)
SHEET_HEADERS = [
    "Название",
    "ИНН",
    "Цена",
    "Дата регистрации",
    "Налог",
    "Адрес и директор",
    "Суды",
    "Долги / ИЛ",
    "Достоверность ЕГРЮЛ",
    "Банкротство",
    "Обороты",
    "Отчётность",
    "Лизинг / залоги",
    "ЗСК",
    "Итог",
    "Балл",
    "Первое появление",
    "Продавец",
    "Ссылка",
    "Companium",
    "Статус ЕГРЮЛ",
]

VERDICT_COL = 15  # 1-based для Apps Script
ZSK_COL = 14

_WS = re.compile(r"\s+")
_BUYER_PREFIXES = (
    "добрый",
    "здравствуйте",
    "всем привет",
    "подскажите",
    "нужна",
    "нужен",
    "нужно",
    "ищу",
    "куплю",
    "требуется",
    "помогите",
    "есть кто",
    "кто прода",
)
_BUYER_TEXT = re.compile(
    r"(?i)\b(нужна|нужен|нужно|ищу|куплю|требуется|подберите)\b|"
    r"добрый\s+день|здравствуйте"
)
_SALE_HINT = re.compile(
    r"(?i)\b(прода[еёю]|продажа|стоимость|цена)\b|\bИНН\s*[:\-]?\s*\d{10}"
)


def _is_buyer_name(name: str) -> bool:
    low = (name or "").strip().lower()
    if not low:
        return False
    return any(low.startswith(p) for p in _BUYER_PREFIXES)



def _flat(s: Any, limit: int = 300) -> str:
    if s is None:
        return ""
    t = str(s).replace("\r\n", " ").replace("\n", " ").replace("\r", " ")
    t = _WS.sub(" ", t).strip()
    return t[:limit]


def _payload_inn(p: dict[str, Any]) -> str:
    inn = (p.get("inn") or "").strip()
    if inn.isdigit() and len(inn) == 10:
        return inn
    egrul = (p.get("enrich") or {}).get("egrul") or {}
    e_inn = (egrul.get("inn") or "").strip()
    if e_inn.isdigit() and len(e_inn) == 10:
        return e_inn
    return ""


def _display_name(p: dict[str, Any]) -> str:
    from parser.extract import is_plausible_firm_name

    egrul = (p.get("enrich") or {}).get("egrul") or {}
    inn = _payload_inn(p)
    # 1) официальное из ЕГРЮЛ — всегда优先тет
    eg = _flat(egrul.get("name") or egrul.get("name_full") or "", 120)
    if eg:
        if not eg.upper().startswith("ООО"):
            eg = f"ООО «{eg}»"
        return eg
    # 2) нормальное имя из поста
    name = _flat(p.get("name") or "", 120)
    if name and not _is_buyer_name(name) and is_plausible_firm_name(name):
        return name
    if inn:
        return f"ООО (ИНН {inn})"
    return "без названия"


def _turnover_cell(p: dict[str, Any], cl: dict[str, Any], sc: dict[str, Any]) -> str:
    """Обороты: БФО отдельно от цифр «из поста» (чтобы не путать)."""
    buh = (p.get("enrich") or {}).get("buh") or {}
    r = str(cl.get("R_turnover") or "").strip()
    if r and buh.get("years") and not buh.get("error"):
        if r.startswith("БФО:"):
            return _flat(r, 80)
        return _flat(f"БФО: {r}", 80)
    if r.startswith("Companium:"):
        return _flat(r, 80)
    if r.startswith("есть") or r.startswith("мало") or "выручка" in r:
        # checklist от buh, но блок buh мог не сохраниться
        return _flat(f"БФО: {r}", 80)
    # цифры только из текста объявления — помечаем явно
    flag = str(sc.get("has_turnover_flag") or "")
    tg = p.get("revenues") or {}
    if tg or (flag.startswith("есть") or flag.startswith("мало")):
        raw = flag or "есть цифры"
        return _flat(f"только в посте (не БФО): {raw}", 80)
    return "нет данных"


def is_sheet_worthy(p: dict[str, Any]) -> bool:
    """В Sheets — только лоты с реальным ИНН (10 цифр)."""
    if p.get("is_duplicate"):
        return False
    return bool(_payload_inn(p))


def _short_verdict(p: dict[str, Any]) -> str:
    """Полный текст итога — не режем до 220 символов."""
    sc = p.get("scoring") or {}
    summary = _flat(sc.get("summary") or "", 4000)
    if summary:
        return summary
    v = (sc.get("verdict") or "").strip()
    return v or "нет оценки"


def sheet_row(p: dict[str, Any]) -> list[Any]:
    enrich = p.get("enrich") or {}
    cl = enrich.get("checklist") or {}
    egrul = enrich.get("egrul") or {}
    sc = p.get("scoring") or {}
    price = p.get("price_rub")
    f_parts = []
    if cl.get("F_address"):
        f_parts.append(str(cl["F_address"]))
    if cl.get("F_director"):
        f_parts.append(str(cl["F_director"]))
    dossier = _flat(cl.get("dossier") or "", 220)
    i_txt = _human_flag("I_reliable", cl.get("I_reliable")) or "нет данных"
    u_txt = _human_flag("U_reports_filed", cl.get("U_reports_filed")) or "нет данных"
    o_txt = _flat(cl.get("O_clean") or "", 60) or "нет данных"
    # пустые суды/долги — явно, не молчание
    p_txt = _flat(cl.get("P_court_cases") or "", 40) or "нет данных"
    l_txt = _flat(cl.get("L_debts_il") or "", 40) or "нет данных"
    v_txt = _flat(cl.get("V_leases") or cl.get("V_note") or "", 80) or "нет данных"
    return [
        _display_name(p),
        _payload_inn(p),
        price if price is not None else "",
        _flat(cl.get("C_reg_date") or egrul.get("reg_date") or p.get("reg_date_raw") or "", 40),
        _flat(p.get("sno") or "", 20),
        _flat(" | ".join(f_parts), 200) or "нет данных",
        p_txt,
        l_txt,
        i_txt,
        o_txt,
        _turnover_cell(p, cl, sc),
        u_txt,
        v_txt,
        _zsk_cell(p.get("zsk_claim") or ""),
        _short_verdict(p),
        # строка, иначе Sheets воспринимает 91 как дату 1900-04-01
        "" if sc.get("score") in (None, "") else str(int(sc.get("score"))),
        (p.get("listing_first_seen") or p.get("msg_date") or "")[:10],
        _flat(p.get("seller_username") or p.get("seller_from_msg") or "", 40),
        p.get("link") or "",
        dossier,
        _flat(cl.get("status") or egrul.get("status") or "", 40),
    ]


def export_apps_script(
    payloads: list[dict[str, Any]],
    *,
    skip_duplicates: bool = True,
) -> str:
    url = (GOOGLE_APPS_SCRIPT_URL or "").strip()
    if not url:
        raise SystemExit("В .env нет GOOGLE_APPS_SCRIPT_URL")

    if skip_duplicates:
        payloads = [p for p in payloads if not p.get("is_duplicate")]

    before = len(payloads)
    payloads = [p for p in payloads if is_sheet_worthy(p)]
    skipped = before - len(payloads)

    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for p in payloads:
        groups[_first_seen_day(p)].append(p)
    days = sorted(groups.keys(), reverse=True)

    sheets: list[dict[str, Any]] = []
    used: set[str] = set()
    for day in days:
        title = _sheet_title(day)
        base, n = title, 2
        while title in used:
            title = f"{base}_{n}"[:90]
            n += 1
        used.add(title)
        rows_src = sorted(
            groups[day],
            key=lambda p: int((p.get("scoring") or {}).get("score") or 0),
            reverse=True,
        )
        sheets.append(
            {
                "name": title,
                "headers": SHEET_HEADERS,
                "rows": [sheet_row(p) for p in rows_src],
            }
        )

    if not sheets:
        sheets = [{"name": "пусто", "headers": SHEET_HEADERS, "rows": []}]

    body = {
        "sheets": sheets,
        "verdictCol": VERDICT_COL,
        "zskCol": ZSK_COL,
        "version": EXPORT_VERSION,
    }
    token = (GOOGLE_APPS_SCRIPT_TOKEN or "").strip()
    post_url = url
    if token:
        sep = "&" if "?" in url else "?"
        post_url = f"{url}{sep}{urlencode({'token': token})}"

    req = Request(
        post_url,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    with urlopen(req, timeout=180) as resp:
        raw = resp.read().decode("utf-8", "replace")
    try:
        data = json.loads(raw)
    except Exception:
        raise SystemExit(f"Apps Script ответ не JSON: {raw[:400]}")

    if not data.get("ok"):
        raise SystemExit(f"Apps Script error: {data}")

    names = data.get("names") or []
    print(
        f"Google Sheets [{EXPORT_VERSION}]: ok | строк={data.get('rows')} | "
        f"листов={data.get('sheets')} | отброшено_мусора={skipped} | "
        f"script={data.get('version')} | "
        f"вкладки={', '.join(names[:10])}{'…' if len(names) > 10 else ''}"
    )
    if data.get("version") != EXPORT_VERSION:
        print(
            "⚠ В Google всё ещё СТАРЫЙ Apps Script. "
            "Замените код в редакторе и сделайте Новую версию развёртывания."
        )
    return url
