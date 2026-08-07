from __future__ import annotations

from pathlib import Path
from typing import Any

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

HEADERS = [
    "A Название",
    "B ИНН",
    "C Дата рег.",
    "D Цена",
    "E Цена покупки (вручную)",
    "F Регистрация (+адрес)",
    "G ОСНО/СНО",
    "H Рег до 2024",
    "I Достоверность (вручную/ФНС)",
    "J Первичка/1С (вручную)",
    "K Займы, кредиторка",
    "L Долги/ИЛ",
    "M Не на ликвидации",
    "N Не на исключении",
    "O Банкрот/дисквал/санкции",
    "P Судебные дела",
    "Q Расчётные счета (вручную)",
    "R Есть обороты (>500к)",
    "S ЗСК (заявление продавца)",
    "T Приостановки (вручную)",
    "U Отчётность сдана",
    "V Лизинги/кредиты",
    "W Дата проверки",
    "X Результат ИИ/скоринг",
    "Ссылка",
    "Продавец",
    "Score",
    "ОГРН",
    "ОКВЭД",
    "Уверенность",
    "ЕГРЮЛ статус",
    "Дубликат",
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
        "green": "🟢 зелёный (заявление)",
        "yellow": "🟡 жёлтый (заявление)",
        "red": "🔴 красный (заявление)",
    }.get(claim, "")


def _price_cell(price: int | None) -> str | int:
    return price if price is not None else ""


def row_from_payload(p: dict[str, Any]) -> list[Any]:
    scoring = p.get("scoring") or {}
    enrich = p.get("enrich") or {}
    checklist = enrich.get("checklist") or {}
    egrul = enrich.get("egrul") or {}

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

    return [
        p.get("name") or egrul.get("name") or "",
        inn,
        checklist.get("C_reg_date") or p.get("reg_date_raw") or "",
        _price_cell(p.get("price_rub")),
        "",  # E manual
        f_cell,  # F from EGRUL (+ manual later)
        p.get("sno") or "",
        scoring.get("reg_before_2024") or "",
        "",  # I
        j_hint,
        checklist.get("K_loans_payables") or "",
        checklist.get("L_debts_il")
        or ("продавец: без долгов" if p.get("no_debts_claim") else ""),
        checklist.get("M_not_liquidating") or "",
        checklist.get("N_not_excluding") or "",
        "",  # O
        checklist.get("P_court_cases") or "",
        q_hint,
        checklist.get("R_turnover") or scoring.get("has_turnover_flag") or "",
        _zsk_cell(p.get("zsk_claim") or ""),
        t_hint,
        checklist.get("U_reports_filed") or "",
        "",  # V
        enrich.get("checked_at") or p.get("msg_date") or "",
        scoring.get("summary") or "",
        p.get("link") or "",
        p.get("seller_username") or p.get("seller_from_msg") or "",
        scoring.get("score") or "",
        p.get("ogrn") or egrul.get("ogrn") or "",
        p.get("okved") or egrul.get("okved") or "",
        scoring.get("confidence") or "",
        checklist.get("status") or egrul.get("status") or "",
        "ДА" if p.get("is_duplicate") else "",
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
        7: 12,
        19: 22,
        24: 50,
        25: 28,
        26: 16,
        33: 50,
    }
    for i in range(1, len(HEADERS) + 1):
        ws.column_dimensions[get_column_letter(i)].width = widths.get(i, 14)
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = (
        f"A1:{get_column_letter(len(HEADERS))}{max(1, len(payloads) + 1)}"
    )

    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    return path
