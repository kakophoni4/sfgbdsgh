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


def _flag(checklist: dict, key: str) -> str:
    """ok | bad | check | '' — с учётом старых ДА/НЕТ и новых фраз в БД."""
    raw = str(checklist.get(key) or "").strip()
    if not raw:
        return ""
    low = raw.lower()
    if "провер" in low:
        return "check"
    if key == "O_clean":
        if low in {"да", "нет банкротства"}:
            return "ok"
        if low == "нет" or low.startswith("есть"):
            return "bad"
        return ""
    if key == "L_debts_il":
        if low in {"да", "нет долгов/ил"}:
            return "ok"
        if low in {"нет", "есть долги/ил"}:
            return "bad"
        return ""
    if key == "P_court_cases":
        if low in {"нет", "нет дел"}:
            return "ok"
        if low in {"есть", "есть дела"}:
            return "bad"
        return ""
    if key == "V_leases":
        if low in {"нет", "нет лизинга/залогов"}:
            return "ok"
        if low in {"есть", "есть лизинг/залоги"}:
            return "bad"
        if "есть записи" in low:
            return "warn"  # сообщения на Федресурсе есть, тип не разобран
        return ""
    if key in {"M_not_liquidating", "N_not_excluding", "I_reliable"}:
        if low == "да":
            return "ok"
        if low == "нет":
            return "bad"
        return ""
    return ""


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

    r_raw = str(buh_cl.get("R_turnover") or "")
    if turn_buh >= 500_000 or r_raw.startswith("есть") or r_raw == "ЕСТЬ":
        score += 14
        reasons.append(
            f"обороты по БФО ≥ 500к (макс ~{(turn_buh or turn):,} ₽)".replace(",", " ")
        )
        # цена vs обороты — в _price_judgment (чтобы не дублировать)
    elif r_raw.startswith("мало") or r_raw in {"НЕТ", "отчётность есть, выручка не указана"}:
        score -= 6
        risks.append("по БФО обороты ≤ 500к / выручка не указана")
    elif r_raw.startswith("нет данных"):
        score -= 3
        risks.append("карточки БФО нет")
    elif zero and turn < 500_000:
        score -= 6
        risks.append("без оборотов / нулёвка (заявление)")
    elif turn_tg >= 500_000:
        score += 12
        reasons.append(f"обороты в тексте ≥ 500к (макс ~{turn_tg:,} ₽)".replace(",", " "))
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

    # L / P / I / O / V
    fl = _flag(buh_cl, "L_debts_il")
    if fl == "ok":
        score += 6
        reasons.append("ФССП: долгов/ИЛ не видно")
    elif fl == "bad":
        score -= 20
        risks.append("ФССП: есть исполнительные производства")
    elif fl == "check":
        score -= 2
        risks.append("ФССП не проверен автоматически")

    fp = _flag(buh_cl, "P_court_cases")
    if fp == "ok":
        score += 6
        reasons.append("КАД: дел не найдено")
    elif fp == "bad":
        score -= 12
        risks.append("КАД: есть арбитражные дела")
    elif fp == "check":
        score -= 2
        risks.append("КАД не проверен автоматически")

    fi = _flag(buh_cl, "I_reliable")
    if fi == "ok":
        score += 4
        reasons.append("недостоверок в карточке ЕГРЮЛ не видно")
    elif fi == "bad":
        score -= 25
        risks.append("недостоверные сведения в ЕГРЮЛ")
    elif fi == "check":
        score -= 2
        risks.append("достоверность не подтверждена")

    fo = _flag(buh_cl, "O_clean")
    if fo == "ok":
        score += 6
        reasons.append("нет банкротства (Федресурс)")
    elif fo == "bad":
        score -= 40
        risks.append("банкротство / дисквал (O)")
    elif fo == "check":
        score -= 3
        risks.append("O (банкротство) не проверен")

    fv = _flag(buh_cl, "V_leases")
    if fv == "ok":
        score += 3
        reasons.append("нет лизинга/залогов в Федресурсе")
    elif fv == "bad":
        score -= 8
        risks.append("есть лизинг/залоги (Федресурс)")
    elif fv == "warn":
        score -= 5
        risks.append("на Федресурсе есть записи — открой ссылку (лизинг/залоги?)")
    elif fv == "check":
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

    # Как давно / как часто продают в чате
    listing_days = int(p.get("listing_days") or 0)
    listing_count = int(p.get("listing_count") or 1)
    if listing_count >= 4 or listing_days >= 45:
        score -= 8
        risks.append(
            f"долго в продаже: {listing_count} объявл., ~{listing_days} дн. в чате"
        )
    elif listing_count >= 2 or listing_days >= 14:
        score -= 3
        risks.append(
            f"повторяется в чате: {listing_count} объявл., ~{listing_days} дн."
        )
    elif listing_count == 1 and listing_days == 0:
        reasons.append("свежее объявление (один раз в выборке)")

    price = p.get("price_rub")
    price_view = _price_judgment(price=price, turn=turn, reg_year=reg_year, r_raw=r_raw)
    if price_view["delta"]:
        score += price_view["delta"]
    if price_view["risk"]:
        risks.append(price_view["risk"])
    if price_view["reason"]:
        reasons.append(price_view["reason"])

    score = max(0, min(100, score))

    hard_no = (
        zsk == "red"
        or _flag(checklist, "M_not_liquidating") == "bad"
        or _flag(checklist, "N_not_excluding") == "bad"
        or _flag(checklist, "O_clean") == "bad"
        or _flag(checklist, "I_reliable") == "bad"
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

    summary = _build_human_verdict(
        verdict=verdict,
        label=label,
        score=score,
        confidence=confidence,
        reasons=reasons,
        risks=risks,
        p=p,
        checklist=checklist,
        turn=turn,
        listing_days=listing_days,
        listing_count=listing_count,
        price_view=price_view,
    )

    return {
        "score": score,
        "verdict": verdict,
        "label": label,
        "confidence": confidence,
        "reasons": reasons,
        "risks": risks,
        "price_label": price_view.get("label") or "",
        "summary": summary,
        "turnover_recent": turn,
        "reg_before_2024": "ДА"
        if reg_year and reg_year < 2024
        else ("НЕТ" if reg_year else ""),
        "has_turnover_flag": (
            buh_cl.get("R_turnover")
            or (
                f"есть, макс ~{turn:,} ₽".replace(",", " ")
                if turn >= 500_000
                else (
                    f"мало, макс ~{turn:,} ₽".replace(",", " ")
                    if revenues or zero
                    else "нет данных"
                )
            )
        ),
        "egrul_verified": verified,
        "buh_verified": bool(
            (p.get("enrich") or {}).get("buh", {}).get("years")
            and not (p.get("enrich") or {}).get("buh", {}).get("error")
        ),
    }


def _price_judgment(
    *,
    price: Any,
    turn: int,
    reg_year: Any,
    r_raw: str,
) -> dict[str, Any]:
    """
    Человеческая оценка цены готового ООО относительно рынка и оборотов.
    label — коротко для Итога; delta — к баллу; risk/reason — в списки скоринга.
    """
    out: dict[str, Any] = {
        "label": "",
        "blurb": "",
        "delta": 0,
        "risk": "",
        "reason": "",
    }
    try:
        price_i = int(price) if price not in (None, "") else 0
    except (TypeError, ValueError):
        price_i = 0
    if not price_i:
        out["label"] = "цена неясна"
        out["blurb"] = "Цену из объявления не распознали — сравнивать с рынком нельзя."
        out["delta"] = -8
        out["risk"] = "цена не распознана"
        return out

    price_s = f"{price_i:,} ₽".replace(",", " ")
    young = bool(reg_year and int(reg_year) >= 2024)
    thin_turn = (
        turn < 500_000
        or str(r_raw).startswith("мало")
        or "выручка не указана" in str(r_raw)
        or str(r_raw).startswith("нет данных")
        or not str(r_raw).strip()
    )

    # 1) относительно оборотов БФО/поста (если обороты живые)
    if turn >= 500_000:
        ratio = price_i / turn
        pct = int(round(ratio * 100))
        turn_s = f"{turn:,}".replace(",", " ")
        if ratio <= 0.12:
            out["label"] = "выгодно к оборотам"
            out["blurb"] = (
                f"Цена {price_s} — примерно {pct}% от оборота (~{turn_s} ₽), "
                f"выглядит выгодно относительно выручки."
            )
            out["delta"] = 8
            out["reason"] = "цена низкая относительно оборотов"
        elif ratio <= 0.35:
            out["label"] = "адекватно к оборотам"
            out["blurb"] = (
                f"Цена {price_s} — около {pct}% от оборота (~{turn_s} ₽), "
                f"к выручке выглядит нормально."
            )
            out["delta"] = 3
            out["reason"] = "цена адекватна оборотам"
        elif ratio < 1.0:
            out["label"] = "дороговато к оборотам"
            out["blurb"] = (
                f"Цена {price_s} — уже ~{pct}% от оборота (~{turn_s} ₽): "
                f"дороговато, если не покупаешь за особый актив/лицензию."
            )
            out["delta"] = -6
            out["risk"] = "цена дороговато относительно оборотов"
        else:
            out["label"] = "дорого к оборотам"
            out["blurb"] = (
                f"Цена {price_s} ≥ оборота (~{turn_s} ₽) — "
                f"дорого: либо переплата, либо в цене что-то кроме «пустой» фирмы."
            )
            out["delta"] = -10
            out["risk"] = "цена высокая относительно оборотов"
        return out

    # 2) без живых оборотов — ориентир рынка готовых ООО
    if price_i < 20_000:
        out["label"] = "подозрительно дёшево"
        out["blurb"] = (
            f"Цена {price_s} — очень низкая для ООО; проверь комплект, долги и почему так отдают."
        )
        out["delta"] = -5
        out["risk"] = "очень низкая цена — проверить комплект"
    elif price_i <= 80_000:
        out["label"] = "дешево / типично для нулёвки"
        out["blurb"] = (
            f"Цена {price_s} — в диапазоне недорогих готовых ООО"
            + (" (молодая компания)" if young else "")
            + "; для нулёвки нормально, за живой бизнес маловато."
        )
        out["delta"] = 2 if thin_turn else 0
        out["reason"] = "цена в типичном диапазоне недорогой нулёвки"
    elif price_i <= 400_000:
        out["label"] = "норма по рынку готовых ООО"
        out["blurb"] = (
            f"Цена {price_s} — обычный рынок готовых ООО"
            + (
                ", но оборотов почти нет — платишь за историю/ЗСК/комплект, не за выручку"
                if thin_turn
                else ""
            )
            + "."
        )
        out["delta"] = 3
        out["reason"] = "цена в типичном диапазоне 50–400к"
    elif price_i <= 900_000:
        out["label"] = "дороговато без оборотов" if thin_turn else "выше среднего"
        out["blurb"] = (
            f"Цена {price_s} — уже дороговато"
            + (
                " для фирмы без заметной выручки: либо хороший комплект/возраст, либо переплата"
                if thin_turn
                else " относительно среднего чека готовых ООО"
            )
            + "."
        )
        out["delta"] = -5 if thin_turn else -2
        out["risk"] = "дороговато при слабых/неясных оборотах"
    else:
        out["label"] = "дорого"
        out["blurb"] = (
            f"Цена {price_s} — высокая для готового ООО"
            + (
                " без крупных оборотов: я бы не брал без понятной причины (лицензии, контракты, история)"
                if thin_turn or turn < 10_000_000
                else ""
            )
            + "."
        )
        out["delta"] = -8 if thin_turn or turn < 10_000_000 else -3
        out["risk"] = "дорогая лавка при средних/неясных оборотах"
    return out


def _parse_dossier_bits(dossier: str) -> dict[str, str]:
    """Достаёт числа/факты из строки Companium для живого итога."""
    import re

    d = dossier or ""
    out: dict[str, str] = {}
    m = re.search(r"суды:\s*(нет дел|\d+\s*дел)", d, re.I)
    if m:
        out["courts"] = m.group(1).strip()
    m = re.search(r"долги ФССП:\s*(нет|\d+\s*пр\.)", d, re.I)
    if m:
        out["fssp"] = m.group(1).strip()
    m = re.search(r"сотрудники:\s*(\d+)", d, re.I)
    if m:
        out["employees"] = m.group(1)
    m = re.search(r"уст\.?капитал:\s*([\d\s]+)\s*₽", d, re.I)
    if m:
        out["capital"] = m.group(1).strip()
    m = re.search(r"МСП:\s*([^;]+)", d, re.I)
    if m:
        out["msp"] = m.group(1).strip()
    m = re.search(r"выручка:\s*([^;]+)", d, re.I)
    if m:
        out["rev"] = m.group(1).strip()[:160]
    m = re.search(r"учредитель:\s*([^;]+)", d, re.I)
    if m:
        out["founder"] = m.group(1).strip()[:100]
    m = re.search(r"федресурс:\s*([^;]+)", d, re.I)
    if m:
        out["fed"] = m.group(1).strip()
    m = re.search(r"недостоверки:\s*([^;]+)", d, re.I)
    if m:
        out["unrel"] = m.group(1).strip()
    m = re.search(r"лицензии:\s*([^;]+)", d, re.I)
    if m:
        out["lic"] = m.group(1).strip()[:80]
    if "Companium недоступен" in d:
        out["error"] = d.replace("Companium недоступен:", "").strip()[:80]
    return out


def _build_human_verdict(
    *,
    verdict: str,
    label: str,
    score: int,
    confidence: str,
    reasons: list[str],
    risks: list[str],
    p: dict[str, Any],
    checklist: dict[str, Any],
    turn: int,
    listing_days: int,
    listing_count: int,
    price_view: dict[str, Any] | None = None,
) -> str:
    """Живой полный вердикт: реестры + Companium + финансы + пост."""
    import re

    name = (p.get("name") or checklist.get("B_name") or "Компания").strip()
    price = p.get("price_rub")
    price_s = f"{price:,} ₽".replace(",", " ") if price else "цена не указана"
    inn = (p.get("inn") or "").strip()
    status = str(checklist.get("status") or "").strip()
    director = str(checklist.get("F_director") or "").strip()
    address = str(checklist.get("F_address") or "").strip()
    reg_date = str(checklist.get("C_reg_date") or p.get("reg_date_raw") or "").strip()
    pv = price_view or {}
    price_tag = str(pv.get("label") or "").strip()

    if verdict == "ДА":
        lead = (
            f"Беру в работу: {name} за {price_s}"
            + (f" ({price_tag})" if price_tag else "")
            + f". Оценка {score} из 100 — лот выглядит интересным"
            + (f", ИНН {inn}" if inn else "")
            + "."
        )
    elif verdict == "СОМНИТЕЛЬНО":
        lead = (
            f"Пока на паузе: {name} за {price_s}"
            + (f" ({price_tag})" if price_tag else "")
            + f". Оценка {score} из 100 — "
            f"есть смысл смотреть, но без ручной проверки брать нельзя"
            + (f" (ИНН {inn})" if inn else " (ИНН пока нет)")
            + "."
        )
    else:
        lead = (
            f"Скорее пропускаю: {name} за {price_s}"
            + (f" ({price_tag})" if price_tag else "")
            + f". Оценка {score} из 100 — "
            f"рисков или дыр в данных слишком много"
            + (f", ИНН {inn}" if inn else "")
            + "."
        )

    paras = [lead]
    if pv.get("blurb"):
        paras.append(str(pv["blurb"]))

    # Карточка ЕГРЮЛ одной фразой
    card: list[str] = []
    if status:
        card.append(f"статус «{status}»")
    if reg_date:
        card.append(f"регистрация {reg_date}")
    if director:
        card.append(f"директор: {director}")
    if address:
        addr_short = address if len(address) <= 90 else address[:87] + "…"
        card.append(f"адрес: {addr_short}")
    if card:
        paras.append("По ЕГРЮЛ: " + "; ".join(card) + ".")

    # Реестры — с числами из notes / dossier
    clean: list[str] = []
    dirty: list[str] = []
    p_v = str(checklist.get("P_court_cases") or "")
    l_v = str(checklist.get("L_debts_il") or "")
    o_v = str(checklist.get("O_clean") or "")
    i_v = str(checklist.get("I_reliable") or "")
    v_v = str(checklist.get("V_leases") or "")
    p_note = str(checklist.get("P_note") or "")
    l_note = str(checklist.get("L_note") or "")
    dossier = str(checklist.get("dossier") or "")
    bits = _parse_dossier_bits(dossier)

    if p_v in {"нет дел", "НЕТ"}:
        clean.append("арбитражных дел не видно")
    elif p_v in {"есть дела", "ЕСТЬ"}:
        n_m = re.search(r"дел[а]?=(\d+)", p_note) or re.search(r"(\d+)\s*дел", bits.get("courts", ""))
        if n_m:
            dirty.append(f"в арбитраже {n_m.group(1)} дел — обязательно открой карточки")
        else:
            dirty.append("есть арбитражные дела")
    elif p_v in {"", "ПРОВЕРИТЬ"}:
        dirty.append("суды ещё не проверены")

    if l_v in {"нет долгов/ИЛ", "ДА"}:
        clean.append("по ФССП долгов не видно")
    elif "есть долг" in l_v.lower() or l_v == "НЕТ":
        n_m = re.search(r"производств=(\d+)", l_note) or re.search(
            r"(\d+)\s*пр", bits.get("fssp", "")
        )
        if n_m:
            dirty.append(f"на ФССП {n_m.group(1)} производств")
        else:
            dirty.append("есть долги или исполнительные листы")
    elif l_v in {"", "ПРОВЕРИТЬ"}:
        dirty.append("долги ФССП не проверены")

    if "нет банкрот" in o_v.lower() or o_v == "ДА":
        clean.append("банкротства нет")
    elif o_v.startswith("есть") or o_v == "НЕТ":
        dirty.append("есть признаки банкротства или дисквала")
    elif not o_v or o_v == "ПРОВЕРИТЬ":
        dirty.append("банкротство не проверено")

    if i_v == "ДА":
        clean.append("недостоверных сведений в ЕГРЮЛ не отмечено")
    elif i_v == "НЕТ":
        dirty.append("в ЕГРЮЛ есть отметка о недостоверности")

    if "нет лизинг" in v_v.lower():
        clean.append("лизинга и залогов не видно")
    elif "есть записи" in v_v.lower() or "есть лизинг" in v_v.lower():
        fed = bits.get("fed") or "есть записи"
        dirty.append(f"на Федресурсе {fed} — открой ссылку перед сделкой")

    reg_parts: list[str] = []
    if clean:
        reg_parts.append("По открытым реестрам спокойно: " + ", ".join(clean) + ".")
    if dirty:
        reg_parts.append("Настораживает: " + ", ".join(dirty) + ".")
    if reg_parts:
        paras.append(" ".join(reg_parts))

    # Companium — отдельный человечный абзац
    if bits.get("error"):
        paras.append(
            f"Отчёт Companium не удалось снять ({bits['error']}) — "
            f"по этой карточке картина неполная."
        )
    elif dossier and not bits.get("error"):
        c_bits: list[str] = []
        if bits.get("courts"):
            c_bits.append(
                "судов нет"
                if bits["courts"].startswith("нет")
                else f"суды: {bits['courts']}"
            )
        if bits.get("fssp"):
            c_bits.append(
                "долгов ФССП нет"
                if bits["fssp"] == "нет"
                else f"ФССП: {bits['fssp']}"
            )
        if bits.get("unrel"):
            if bits["unrel"].upper().startswith("ЕСТЬ") or bits["unrel"].lower() == "есть":
                c_bits.append("недостоверки ЕСТЬ")
            else:
                c_bits.append("недостоверок нет")
        if bits.get("employees"):
            c_bits.append(f"{bits['employees']} сотрудник(ов)")
        elif checklist.get("employees") not in (None, ""):
            c_bits.append(f"{checklist.get('employees')} сотрудник(ов)")
        if bits.get("msp"):
            c_bits.append(f"МСП: {bits['msp']}")
        elif checklist.get("msp"):
            c_bits.append(f"МСП: {checklist.get('msp')}")
        if bits.get("capital"):
            c_bits.append(f"уставный капитал {bits['capital']} ₽")
        elif checklist.get("capital_rub") not in (None, ""):
            try:
                c_bits.append(
                    f"уставный капитал {int(checklist['capital_rub']):,} ₽".replace(",", " ")
                )
            except (TypeError, ValueError):
                pass
        if bits.get("rev") and "нет сведений" not in bits["rev"].lower():
            c_bits.append(f"по выручке Companium: {bits['rev']}")
        elif checklist.get("revenue_note"):
            c_bits.append(f"по выручке Companium: {checklist.get('revenue_note')}")
        if bits.get("founder"):
            c_bits.append(f"учредитель: {bits['founder']}")
        elif checklist.get("founder"):
            c_bits.append(f"учредитель: {checklist.get('founder')}")
        if bits.get("lic") and "нет сведений" not in bits["lic"].lower():
            c_bits.append(f"лицензии: {bits['lic']}")
        if c_bits:
            paras.append("Сводка Companium: " + "; ".join(c_bits) + ".")

    # Финансы / возраст
    fin: list[str] = []
    r_v = str(checklist.get("R_turnover") or "")
    u_v = str(checklist.get("U_reports_filed") or "")
    if turn and turn >= 500_000:
        fin.append(f"по БФО обороты заметные (около {turn:,} ₽)".replace(",", " "))
    elif r_v.startswith("есть"):
        fin.append("в отчётности есть выручка выше 500 тыс.")
    elif "выручка не указана" in r_v or r_v.startswith("мало"):
        fin.append(
            "отчётность есть, но живых оборотов почти не видно — "
            "похоже на нулёвку или «пустую» фирму"
        )
    elif r_v.startswith("нет данных") or not r_v:
        fin.append("по финансам ФНС данных мало")
    if u_v in {"ДА", "сдана"} and "отчётность" not in " ".join(fin):
        fin.append("отчётность в базе ФНС сдана")
    elif u_v in {"НЕТ", "не сдана"}:
        fin.append("отчётность в ФНС не сдана или не найдена")

    reg_year = p.get("reg_year")
    if not reg_year and checklist.get("C_reg_date"):
        m = re.search(r"(20\d{2}|19\d{2})", str(checklist.get("C_reg_date")))
        reg_year = int(m.group(1)) if m else None
    if reg_year and reg_year >= 2024:
        fin.append(f"компания молодая ({reg_year} год)")
    elif reg_year and reg_year < 2024:
        fin.append(f"зарегистрирована в {reg_year} — возраст нормальный")
    if fin:
        paras.append("По деньгам и возрасту: " + "; ".join(fin) + ".")

    # Чат / продажа
    if listing_count >= 4 or listing_days >= 14:
        since = (p.get("listing_first_seen") or "")[:10]
        since_bit = f" с {since}" if since else ""
        paras.append(
            f"В чате этот лот уже мелькал {listing_count} раз"
            f" (около {listing_days} дн.{since_bit}) — продают активно, "
            f"возможно, не уходит с первого раза."
        )
    elif listing_count >= 2:
        paras.append(
            f"Объявление повторялось в чате ({listing_count} раз) — не критично, но имейте в виду."
        )
    else:
        paras.append("В выборке лот свежий, раньше почти не светился.")

    # ЗСК и прочее из поста
    zsk = p.get("zsk_claim") or "unknown"
    post_bits: list[str] = []
    if zsk == "green":
        post_bits.append("продавец пишет про «зелёный» ЗСК")
    elif zsk == "yellow":
        post_bits.append("продавец указывает жёлтый ЗСК — осторожнее")
    elif zsk == "red":
        post_bits.append("продавец сам пишет про красный ЗСК — обычно это стоп")
    if p.get("has_account_claim") == "no":
        post_bits.append("в посте сказано, что без расчётного счёта")
    elif p.get("has_account_claim") == "yes":
        post_bits.append("в посте упоминается расчётный счёт")
    if p.get("primary_1c_claim"):
        post_bits.append("обещают первичку/1С")
    sno = (p.get("sno") or "").strip()
    if sno:
        post_bits.append(f"налог в посте: {sno}")
    if post_bits:
        paras.append("Из объявления: " + "; ".join(post_bits) + ".")

    # Хвост
    if confidence == "high":
        tail = "Данных достаточно, чтобы решить: смотреть дальше или нет."
    elif confidence == "medium":
        tail = (
            "Картина собрана неплохо, но перед сделкой всё равно сверьте "
            "выписку ЕГРЮЛ, счета и комплект вручную."
        )
    else:
        tail = "Пока это скорее черновик — не хватает ключевых данных для уверенного решения."

    if verdict == "ДА" and any(
        x in " ".join(risks).lower()
        for x in ("молод", "оборот", "нулёв", "выручка не", "долго в продаж", "повторя")
    ):
        tail += (
            " Несмотря на высокий балл, я бы уточнил обороты и причину продажи — "
            "на бумаге чисто, по сути может быть пустышка."
        )
    elif verdict == "НЕТ":
        tail += " Если очень нужно — только после жёсткой ручной проверки."
    if not dossier:
        tail += " Полного отчёта Companium ещё нет — итог без этой сводки."

    paras.append(tail)
    return " ".join(paras)
