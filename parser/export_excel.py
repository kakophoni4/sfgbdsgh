from __future__ import annotations

from pathlib import Path
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

# Без букв A–X в шапке — понятные названия для заказчика
HEADERS = [
    "Название",
    "ИНН",
    "Дата регистрации",
    "Цена",
    "Цена покупки (вручную)",
    "Адрес и директор",
    "Налоговый режим",
    "Регистрация до 2024",
    "Достоверность ЕГРЮЛ",
    "Первичка / 1С (вручную)",
    "Займы и кредиторка",
    "Долги / исполнительные листы",
    "Не на ликвидации",
    "Не на исключении",
    "Банкротство",
    "Судебные дела",
    "Расчётные счета (вручную)",
    "Обороты (>500 тыс.)",
    "ЗСК (заявление продавца)",
    "Приостановки (вручную)",
    "Отчётность сдана",
    "Лизинг / залоги",
    "Дата проверки",
    "Итог / скоринг",
    "Ссылка на объявление",
    "Продавец",
    "Балл",
    "ОГРН",
    "ОКВЭД",
    "Уверенность",
    "Статус в ЕГРЮЛ",
    "Дубликат",
    "Сводка (Companium)",
    "Сотрудники",
    "МСП",
    "Санкции",
    "Уставный капитал",
    "Налоги (уплачено)",
    "Учредитель",
    "Сырой текст",
]

ZSK_FILL = {
    "green": PatternFill("solid", fgColor="C6EFCE"),
    "yellow": PatternFill("solid", fgColor="FFEB9C"),
    "red": PatternFill("solid", fgColor="FFC7CE"),
}

VERDICT_FILL = {
    "ДА": PatternFill("solid", fgColor="C6EFCE"),
    "НЕТ": PatternFill("solid", fgColor="FFC7CE"),
    "СОМНИТЕЛЬНО": PatternFill("solid", fgColor="FFEB9C"),
}


def _zsk_cell(claim: str) -> str:
    return {
        "green": "зелёный (заявление продавца)",
        "yellow": "жёлтый (заявление продавца)",
        "red": "красный (заявление продавца)",
    }.get(claim, "")


def _price_cell(price: int | None) -> str | int:
    return price if price is not None else ""


def _money(v: Any) -> str:
    if v is None or v == "":
        return ""
    try:
        return f"{int(v):,}".replace(",", " ") + " ₽"
    except (TypeError, ValueError):
        return str(v)


def _human_flag(key: str, val: Any) -> str:
    """Внутренние ДА/НЕТ → понятные фразы в Excel."""
    s = str(val or "").strip()
    if not s:
        return ""
    low = s.lower()
    if key == "I_reliable":
        if low == "да":
            return "достоверно (записи о недостоверности нет)"
        if low == "нет":
            return "есть недостоверность сведений"
        if "провер" in low:
            return "нужно проверить"
    if key in {"M_not_liquidating", "N_not_excluding"}:
        if low == "да":
            return "да"
        if low == "нет":
            return "нет — риск"
    if key == "U_reports_filed":
        if low == "да":
            return "сдана"
        if low == "нет":
            return "не найдена"
    if s == "ПРОВЕРИТЬ":
        return "нужно проверить"
    return s


def row_from_payload(p: dict[str, Any]) -> list[Any]:
    scoring = p.get("scoring") or {}
    enrich = p.get("enrich") or {}
    checklist = enrich.get("checklist") or {}
    egrul = enrich.get("egrul") or {}
    companium = enrich.get("companium") or {}

    j_hint = ""
    if p.get("primary_1c_claim"):
        j_hint = "продавец обещает первичку/1С"
    q_hint = ""
    if p.get("has_account_claim") == "yes":
        q_hint = "в посте есть р/с"
    elif p.get("has_account_claim") == "no":
        q_hint = "без счёта"
    t_hint = "есть блоки в тексте" if p.get("has_blocks_claim") else ""

    f_cell = ""
    if checklist.get("F_address") or checklist.get("F_director"):
        parts = []
        if checklist.get("F_address"):
            parts.append(checklist["F_address"])
        if checklist.get("F_director"):
            parts.append(str(checklist["F_director"]))
        f_cell = " | ".join(parts)

    inn = p.get("inn") or ""
    if not inn and p.get("inn_on_request"):
        inn = "по запросу"

    dossier = checklist.get("dossier") or ""
    if not dossier and companium and not companium.get("error"):
        # старые записи без dossier — коротко из счётчиков
        bits = []
        if companium.get("court_cases") is not None:
            n = companium["court_cases"]
            bits.append("суды: нет дел" if n == 0 else f"суды: {n}")
        if companium.get("enforcements") is not None:
            n = companium["enforcements"]
            bits.append("долги: нет" if n == 0 else f"долги: {n}")
        dossier = "; ".join(bits)

    employees = checklist.get("employees")
    if employees is None:
        employees = companium.get("employees")
    msp = checklist.get("msp") or companium.get("msp") or ""
    sanctions = checklist.get("sanctions") or companium.get("sanctions") or ""
    capital = checklist.get("capital_rub")
    if capital is None:
        capital = companium.get("capital_rub")
    taxes = checklist.get("taxes_rub")
    if taxes is None:
        taxes = companium.get("taxes_rub")
    founder = checklist.get("founder") or companium.get("founder") or ""

    return [
        p.get("name") or egrul.get("name") or "",
        inn,
        checklist.get("C_reg_date") or p.get("reg_date_raw") or "",
        _price_cell(p.get("price_rub")),
        "",  # цена покупки вручную
        f_cell,
        p.get("sno") or "",
        scoring.get("reg_before_2024") or "",
        _human_flag("I_reliable", checklist.get("I_reliable")),
        j_hint,
        checklist.get("K_loans_payables") or "",
        checklist.get("L_debts_il")
        or ("продавец: без долгов" if p.get("no_debts_claim") else ""),
        _human_flag("M_not_liquidating", checklist.get("M_not_liquidating")),
        _human_flag("N_not_excluding", checklist.get("N_not_excluding")),
        checklist.get("O_clean") or "",
        checklist.get("P_court_cases") or "",
        q_hint,
        checklist.get("R_turnover") or scoring.get("has_turnover_flag") or "",
        _zsk_cell(p.get("zsk_claim") or ""),
        t_hint,
        _human_flag("U_reports_filed", checklist.get("U_reports_filed")),
        checklist.get("V_leases") or "",
        enrich.get("checked_at") or p.get("msg_date") or "",
        scoring.get("summary") or "",
        p.get("link") or "",
        p.get("seller_username") or p.get("seller_from_msg") or "",
        scoring.get("score") or "",
        p.get("ogrn") or egrul.get("ogrn") or "",
        p.get("okved") or egrul.get("okved") or "",
        scoring.get("confidence") or "",
        checklist.get("status") or egrul.get("status") or "",
        "да" if p.get("is_duplicate") else "",
        dossier,
        employees if employees is not None else "",
        msp,
        sanctions,
        _money(capital),
        _money(taxes),
        founder,
        (p.get("raw_text") or "")[:2000],
    ]


def export_xlsx(
    payloads: list[dict[str, Any]],
    path: Path,
    *,
    skip_duplicates: bool = True,
) -> Path:
    if skip_duplicates:
        payloads = [p for p in payloads if not p.get("is_duplicate")]

    wb = Workbook()
    ws = wb.active
    ws.title = "Чек-лист"

    header_font = Font(bold=True)
    for col, title in enumerate(HEADERS, 1):
        cell = ws.cell(1, col, title)
        cell.font = header_font
        cell.alignment = Alignment(wrap_text=True, vertical="top")

    # индексы для подсветки (1-based): ЗСК=19, Итог=24
    for r, p in enumerate(payloads, 2):
        values = row_from_payload(p)
        for c, val in enumerate(values, 1):
            cell = ws.cell(r, c, val)
            cell.alignment = Alignment(wrap_text=True, vertical="top")

        zsk = p.get("zsk_claim") or ""
        if zsk in ZSK_FILL:
            ws.cell(r, 19).fill = ZSK_FILL[zsk]
        verdict = (p.get("scoring") or {}).get("verdict")
        if verdict in VERDICT_FILL:
            ws.cell(r, 24).fill = VERDICT_FILL[verdict]

    widths = {
        1: 28,
        2: 14,
        3: 14,
        4: 12,
        6: 36,
        7: 14,
        12: 22,
        15: 18,
        16: 14,
        19: 24,
        24: 48,
        25: 28,
        26: 16,
        33: 56,
        39: 28,
        40: 40,
    }
    for i in range(1, len(HEADERS) + 1):
        ws.column_dimensions[get_column_letter(i)].width = widths.get(i, 14)
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = (
        f"A1:{get_column_letter(len(HEADERS))}{max(1, len(payloads) + 1)}"
    )

    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        wb.save(path)
        return path
    except PermissionError:
        # файл открыт в Excel — пишем рядом с меткой времени
        from datetime import datetime

        alt = path.with_name(
            f"{path.stem}_{datetime.now().strftime('%Y%m%d_%H%M%S')}{path.suffix}"
        )
        wb.save(alt)
        print(f"Excel занят ({path.name}) — сохранено как {alt.name}")
        return alt
