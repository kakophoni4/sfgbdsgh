from __future__ import annotations

from typing import Any

from .extract import Listing


def recent_turnover_from_revenues(revenues: dict | None) -> int:
    if not revenues:
        return 0
    years = sorted(revenues.keys(), reverse=True)
    vals = [revenues[y] for y in years[:3]]
    return max(vals) if vals else 0


def recent_turnover(listing: Listing) -> int:
    return recent_turnover_from_revenues(listing.revenues)


def score_listing(listing: Listing, enrich: dict | None = None) -> dict:
    return score_payload(listing.to_dict() | ({"enrich": enrich} if enrich else {}))


def score_payload(p: dict[str, Any]) -> dict:
    """
    Эвристическая оценка по объявлению + (опционально) ЕГРЮЛ.
    """
    score = 50
    reasons: list[str] = []
    risks: list[str] = []

    inn = (p.get("inn") or "").strip()
    ogrn = (p.get("ogrn") or "").strip()
    enrich = p.get("enrich") or {}
    egrul = enrich.get("egrul") or {}
    checklist = enrich.get("checklist") or {}
    verified = bool(egrul.get("inn") and not egrul.get("error"))

    if inn:
        score += 8
        reasons.append("есть ИНН" + (" (ЕГРЮЛ)" if verified and egrul.get("inn") == inn else ""))
    elif p.get("inn_on_request"):
        score -= 5
        risks.append("ИНН по запросу — нужна ручная проверка")
    elif ogrn:
        score += 4
        reasons.append("есть ОГРН, ИНН можно дотянуть")
    else:
        score -= 10
        risks.append("нет ИНН/ОГРН — обогащение невозможно")

    if verified:
        score += 10
        reasons.append("карточка подтверждена в ЕГРЮЛ")
        flags_m = checklist.get("M_not_liquidating") or ""
        flags_n = checklist.get("N_not_excluding") or ""
        if flags_m == "НЕТ":
            score -= 35
            risks.append("ликвидация/процесс ликвидации (ЕГРЮЛ)")
        elif flags_m == "ДА":
            score += 4
            reasons.append("не на ликвидации")
        if flags_n == "НЕТ":
            score -= 35
            risks.append("исключение из ЕГРЮЛ / недействующая")
        elif flags_n == "ДА":
            score += 4
            reasons.append("не на исключении")

    zsk = p.get("zsk_claim") or "unknown"
    if zsk == "green":
        score += 12
        reasons.append("продавец заявляет зелёный ЗСК")
    elif zsk == "yellow":
        score -= 8
        risks.append("жёлтый ЗСК (заявление продавца)")
    elif zsk == "red":
        score -= 40
        risks.append("красный ЗСК — недопустимо по чек-листу")
    else:
        score -= 3
        risks.append("ЗСК не указан в посте")

    reg_year = p.get("reg_year")
    if not reg_year and checklist.get("C_reg_date"):
        import re

        m = re.search(r"(20\d{2}|19\d{2})", checklist["C_reg_date"])
        reg_year = int(m.group(1)) if m else None

    if reg_year:
        if reg_year < 2024:
            score += 10
            reasons.append(f"регистрация до 2024 ({reg_year})")
        else:
            score -= 4
            risks.append(f"молодая компания ({reg_year})")

    # Обороты: приоритет БФО (ФНС), затем текст объявления
    buh_cl = checklist
    buh_revs = buh_cl.get("revenues") if isinstance(buh_cl.get("revenues"), dict) else {}
    tg_revs = p.get("revenues") or {}
    turn_buh = recent_turnover_from_revenues(buh_revs)
    turn_tg = recent_turnover_from_revenues(tg_revs)
    turn = turn_buh or turn_tg
    zero = bool(p.get("zero_turnover_claim"))
    revenues = buh_revs or tg_revs

    if buh_cl.get("R_turnover") == "ЕСТЬ" or turn_buh >= 500_000:
        score += 14
        reasons.append(
            f"обороты по БФО ≥ 500к (макс ~{(turn_buh or turn):,} ₽)".replace(",", " ")
        )
        price = p.get("price_rub")
        if price and turn > 0 and price / turn <= 0.15:
            score += 8
            reasons.append("цена низкая относительно оборотов БФО")
        elif price and turn > 0 and price / turn >= 1.0:
            score -= 10
            risks.append("цена высокая относительно оборотов БФО")
    elif buh_cl.get("R_turnover") == "НЕТ":
        score -= 6
        risks.append("по БФО обороты ≤ 500к / нули")
    elif zero and turn < 500_000:
        score -= 6
        risks.append("без оборотов / нулёвка (заявление)")
    elif turn_tg >= 500_000:
        score += 12
        reasons.append(f"обороты в тексте ≥ 500к (макс ~{turn_tg:,} ₽)".replace(",", " "))
        price = p.get("price_rub")
        if price and turn_tg > 0:
            ratio = price / turn_tg
            if ratio <= 0.15:
                score += 8
                reasons.append("цена выглядит низкой относительно оборотов")
            elif ratio >= 1.0:
                score -= 10
                risks.append("цена высокая относительно заявленных оборотов")
    elif tg_revs:
        score -= 4
        risks.append("обороты в тексте < 500к")

    if buh_cl.get("U_reports_filed") == "ДА":
        score += 5
        reasons.append("отчётность есть в БФО ФНС")
    elif buh_cl.get("U_reports_filed") == "НЕТ":
        score -= 8
        risks.append("отчётность в БФО не найдена")

    if buh_cl.get("K_loans_payables"):
        k = str(buh_cl["K_loans_payables"])
        if "не указаны / 0" in k:
            score += 2
            reasons.append("займы/кредиторка по БФО пустые/0")
        elif "займы=" in k or "кредиторка=" in k:
            score -= 2
            risks.append("есть займы/кредиторка по БФО")

    # L / P из ФССП / КАД
    if buh_cl.get("L_debts_il") == "ДА":
        score += 6
        reasons.append("ФССП: долгов/ИЛ не видно")
    elif buh_cl.get("L_debts_il") == "НЕТ":
        score -= 20
        risks.append("ФССП: есть исполнительные производства")
    elif buh_cl.get("L_debts_il") == "ПРОВЕРИТЬ":
        score -= 2
        risks.append("ФССП не проверен автоматически")

    if buh_cl.get("P_court_cases") == "НЕТ":
        score += 6
        reasons.append("КАД: дел не найдено")
    elif buh_cl.get("P_court_cases") == "ЕСТЬ":
        score -= 12
        risks.append("КАД: есть арбитражные дела")
    elif buh_cl.get("P_court_cases") == "ПРОВЕРИТЬ":
        score -= 2
        risks.append("КАД не проверен автоматически")

    if buh_cl.get("I_reliable") == "ДА":
        score += 4
        reasons.append("недостоверок в карточке ЕГРЮЛ не видно")
    elif buh_cl.get("I_reliable") == "НЕТ":
        score -= 25
        risks.append("недостоверные сведения в ЕГРЮЛ")
    elif buh_cl.get("I_reliable") == "ПРОВЕРИТЬ":
        score -= 2
        risks.append("достоверность не подтверждена")

    if buh_cl.get("O_clean") == "ДА":
        score += 6
        reasons.append("банкротства/ЕФРСБ не видно")
    elif buh_cl.get("O_clean") == "НЕТ":
        score -= 40
        risks.append("банкротство / дисквал / санкционный риск (O)")
    elif buh_cl.get("O_clean") == "ПРОВЕРИТЬ":
        score -= 3
        risks.append("O (ЕФРСБ/дисквал) не проверен")

    if buh_cl.get("V_leases") == "НЕТ":
        score += 3
        reasons.append("лизинг/залоги в Федресурсе не найдены")
    elif buh_cl.get("V_leases") == "ЕСТЬ":
        score -= 8
        risks.append("есть лизинг/залоги (Федресурс)")
    elif buh_cl.get("V_leases") == "ПРОВЕРИТЬ":
        score -= 1
        risks.append("V (лизинг) не проверен")

    if p.get("has_account_claim") == "no":
        score -= 5
        risks.append("без расчётного счёта")
    elif p.get("has_account_claim") == "yes":
        score += 3
        reasons.append("есть упоминание р/с")

    if p.get("has_blocks_claim"):
        score -= 15
        risks.append("упоминаются блоки/приостановки")

    if p.get("no_debts_claim"):
        score += 4
        reasons.append("продавец пишет «без долгов»")

    if p.get("primary_1c_claim"):
        score += 3
        reasons.append("обещают первичку/1С")

    price = p.get("price_rub")
    if price:
        if price < 20_000:
            score -= 5
            risks.append("очень низкая цена — проверить комплект")
        elif 50_000 <= price <= 400_000:
            score += 3
        elif price >= 1_500_000 and turn < 10_000_000:
            score -= 6
            risks.append("дорогая лавка при средних/неясных оборотах")
    else:
        score -= 8
        risks.append("цена не распознана")

    score = max(0, min(100, score))

    hard_no = (
        zsk == "red"
        or checklist.get("M_not_liquidating") == "НЕТ"
        or checklist.get("N_not_excluding") == "НЕТ"
        or checklist.get("O_clean") == "НЕТ"
        or checklist.get("I_reliable") == "НЕТ"
    )

    if hard_no:
        verdict = "НЕТ"
        label = "отсев"
    elif score >= 72 and inn:
        verdict = "ДА"
        label = "стоит смотреть"
    elif score >= 72 and not inn:
        verdict = "СОМНИТЕЛЬНО"
        label = "похоже ок, но нужен ИНН"
    elif score >= 55:
        verdict = "СОМНИТЕЛЬНО"
        label = "на проверку"
    else:
        verdict = "НЕТ"
        label = "слабо / риски"

    confidence = "low"
    if inn and price and zsk != "unknown":
        confidence = "medium"
    buh_ok = bool(
        ((p.get("enrich") or {}).get("buh") or {}).get("years")
        and not ((p.get("enrich") or {}).get("buh") or {}).get("error")
    )
    if verified and inn and price:
        confidence = "high"
    if buh_ok and inn and price:
        confidence = "high" if confidence != "low" else "medium"
    if not inn:
        confidence = "low"

    summary_parts = []
    if reasons:
        summary_parts.append("Плюсы: " + "; ".join(reasons[:5]))
    if risks:
        summary_parts.append("Риски: " + "; ".join(risks[:5]))
    summary = " | ".join(summary_parts) if summary_parts else "мало данных"

    return {
        "score": score,
        "verdict": verdict,
        "label": label,
        "confidence": confidence,
        "reasons": reasons,
        "risks": risks,
        "summary": f"{verdict} ({label}, {score}/100, conf={confidence}). {summary}",
        "turnover_recent": turn,
        "reg_before_2024": "ДА"
        if reg_year and reg_year < 2024
        else ("НЕТ" if reg_year else ""),
        "has_turnover_flag": (
            buh_cl.get("R_turnover")
            or (
                "ЕСТЬ"
                if turn >= 500_000
                else ("НЕТ" if revenues or zero else "")
            )
        ),
        "egrul_verified": verified,
        "buh_verified": bool(
            (p.get("enrich") or {}).get("buh", {}).get("years")
            and not (p.get("enrich") or {}).get("buh", {}).get("error")
        ),
    }
