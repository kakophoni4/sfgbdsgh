from __future__ import annotations

import random
import re
import time
from datetime import datetime, timezone
from typing import Any, Callable

from config import ENRICH_JITTER, ENRICH_PAUSE
from parser.db import ListingDB
from parser.score import score_payload

from .buh import checklist_from_buh, fetch_buh
from .checko import checklist_from_checko, fetch_checko
from .companium import checklist_from_companium, fetch_companium
from .egrul import lookup_company, status_flags
from .fedresurs import (
    checklist_from_fedresurs,
    fetch_disqualified,
    fetch_fedresurs,
    merge_o_disqualified,
)
from .fssp import checklist_from_fssp, fetch_fssp
from .kad import checklist_from_kad, fetch_kad
from .saby import checklist_from_saby, fetch_saby
from .unreliable import check_unreliable_from_egrul, checklist_from_unreliable

_GAP = frozenset({"", "ПРОВЕРИТЬ"})


def _is_gap(val: Any) -> bool:
    return val is None or val in _GAP


def _checklist_fill_gaps(old: dict[str, Any], new: dict[str, Any]) -> dict[str, Any]:
    """Дописать только пустые/ПРОВЕРИТЬ поля (запасные источники не затирают удачные)."""
    # старые ДА/НЕТ → актуальные подписи, чтобы не смешивать с «нет банкротства»
    out = _remap_checklist_labels(dict(old))
    groups = {
        "P_court_cases": ("P_note", "P_link"),
        "L_debts_il": ("L_note", "L_link"),
        "I_reliable": ("I_note",),
        "V_leases": ("V_note", "V_link"),
        "O_clean": ("O_note", "O_link"),
    }
    for main, extras in groups.items():
        if main not in new:
            continue
        cur = out.get(main)
        nxt = new[main]
        # O: можно «ухудшить» до есть банкротство/дисквал
        o_upgrade = (
            main == "O_clean"
            and str(nxt).startswith("есть")
            and not str(cur or "").startswith("есть")
        )
        # синонимы O: ДА ≡ нет банкротства — не считаем «уже заполнено» блокером новой фразы
        if main == "O_clean" and cur in {"ДА", "нет банкротства"} and nxt == "нет банкротства":
            out[main] = nxt
            for e in extras:
                if e in new:
                    out[e] = new[e]
            continue
        if _is_gap(cur) or o_upgrade:
            out[main] = nxt
            for e in extras:
                if e in new:
                    out[e] = new[e]
    _EXTRA_KEEP = {
        "dossier",
        "employees",
        "msp",
        "sanctions",
        "capital_rub",
        "taxes_rub",
        "insurance_rub",
        "revenue_note",
        "licenses",
        "checks",
        "founder",
        "bankruptcy_reg",
    }
    for k, v in new.items():
        if (
            k.endswith("_url")
            or k.endswith("_error")
            or k.startswith("checko")
            or k.startswith("saby")
            or k.startswith("companium")
            or k in _EXTRA_KEEP
        ):
            if k in _EXTRA_KEEP and not _is_gap(out.get(k)) and _is_gap(v):
                continue
            if k in _EXTRA_KEEP and v in (None, ""):
                continue
            out[k] = v
    return _remap_checklist_labels(out)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _flag_o_needs_retry(cl: dict[str, Any]) -> bool:
    """Нет O / старые ДА/НЕТ / ПРОВЕРИТЬ, либо дыра в V (лизинг) — снова Федресурс."""
    o = cl.get("O_clean")
    if not o or o in {"ДА", "НЕТ", "ПРОВЕРИТЬ"}:
        return True
    return _is_gap(cl.get("V_leases"))


def _remap_checklist_labels(cl: dict[str, Any]) -> dict[str, Any]:
    """Старые ДА/НЕТ → понятные фразы (без сети)."""
    out = dict(cl)
    o = out.get("O_clean")
    if o == "ДА":
        out["O_clean"] = "нет банкротства"
    elif o == "НЕТ":
        note = (out.get("O_note") or "").lower()
        if "дисквал" in note and "банкрот" not in note:
            out["O_clean"] = "есть дисквал"
        else:
            out["O_clean"] = "есть банкротство"
    l = out.get("L_debts_il")
    if l == "ДА":
        out["L_debts_il"] = "нет долгов/ИЛ"
    elif l == "НЕТ":
        out["L_debts_il"] = "есть долги/ИЛ"
    p = out.get("P_court_cases")
    if p == "НЕТ":
        out["P_court_cases"] = "нет дел"
    elif p == "ЕСТЬ":
        out["P_court_cases"] = "есть дела"
    v = out.get("V_leases")
    if v == "НЕТ":
        out["V_leases"] = "нет лизинга/залогов"
    elif v == "ЕСТЬ":
        out["V_leases"] = "есть лизинг/залоги"
    elif v == "ПРОВЕРИТЬ" and "сообщ" in str(out.get("V_note") or "").lower():
        # старые прогоны: был счётчик сообщений, но писали «проверить»
        out["V_leases"] = "есть записи"
    return out


def _sleep(pause: float | None = None) -> float:
    base = ENRICH_PAUSE if pause is None else pause
    delay = max(0.5, base + random.uniform(0, max(0.0, ENRICH_JITTER)))
    time.sleep(delay)
    return delay


def _reg_year(reg_date: str) -> int | None:
    m = re.search(r"(20\d{2}|19\d{2})", reg_date or "")
    return int(m.group(1)) if m else None


def _merge_enrich(p: dict[str, Any], **parts: Any) -> dict[str, Any]:
    enrich = dict(p.get("enrich") or {})
    enrich["checked_at"] = _now()
    for k, v in parts.items():
        if k == "checklist" and isinstance(v, dict):
            cl = dict(enrich.get("checklist") or {})
            cl.update(v)
            enrich["checklist"] = cl
        else:
            enrich[k] = v
    p["enrich"] = enrich
    p["scoring"] = score_payload(p)
    return p


def apply_egrul(payload: dict[str, Any], pause: float = 1.8) -> dict[str, Any]:
    p = dict(payload)
    inn = (p.get("inn") or "").strip()
    ogrn = (p.get("ogrn") or "").strip()
    name = (p.get("name") or "").strip()

    if not inn and not ogrn and not name:
        return _merge_enrich(p, egrul={"error": "no_key"})

    rec = lookup_company(inn=inn, ogrn=ogrn, name=name)
    _sleep(pause)

    if rec.error:
        return _merge_enrich(p, egrul=rec.to_dict())

    if rec.inn and not inn:
        p["inn"] = rec.inn
    if rec.ogrn and not ogrn:
        p["ogrn"] = rec.ogrn
    # Всегда официальное имя из ЕГРЮЛ (не «ООО с историей…» из поста)
    if rec.name:
        p["name"] = (
            rec.name
            if str(rec.name).upper().startswith("ООО")
            else f"ООО «{rec.name}»"
        )
    if rec.reg_date:
        p["reg_date_raw"] = rec.reg_date
        p["reg_year"] = _reg_year(rec.reg_date)
    if rec.okved and not p.get("okved"):
        p["okved"] = rec.okved

    flags = status_flags(rec.status)
    egrul_dict = rec.to_dict()
    checklist = {
        "F_address": rec.address,
        "F_director": rec.director,
        "C_reg_date": rec.reg_date,
        "M_not_liquidating": flags["M"],
        "N_not_excluding": flags["N"],
        "status": flags["status"],
        "kpp": rec.kpp,
    }
    checklist.update(checklist_from_unreliable(check_unreliable_from_egrul(egrul_dict)))
    return _merge_enrich(p, egrul=egrul_dict, checklist=checklist)


def apply_buh(payload: dict[str, Any], pause: float = 1.0) -> dict[str, Any]:
    p = dict(payload)
    inn = (p.get("inn") or "").strip()
    if not inn:
        return _merge_enrich(p, buh={"error": "no_inn"})

    report = fetch_buh(inn, pause=min(pause, 2.0) if pause else 1.0)
    _sleep(pause)
    if report.error:
        return _merge_enrich(p, buh=report.to_dict())
    return _merge_enrich(p, buh=report.to_dict(), checklist=checklist_from_buh(report))


def apply_kad(payload: dict[str, Any], pause: float = 1.0) -> dict[str, Any]:
    p = dict(payload)
    inn = (p.get("inn") or "").strip()
    if not inn:
        return _merge_enrich(p, kad={"error": "no_inn"})
    report = fetch_kad(inn)
    _sleep(pause)
    old = dict((p.get("enrich") or {}).get("checklist") or {})
    return _merge_enrich(
        p,
        kad=report.to_dict(),
        checklist=_checklist_fill_gaps(old, checklist_from_kad(report)),
    )


def apply_fssp(payload: dict[str, Any], pause: float = 1.0) -> dict[str, Any]:
    p = dict(payload)
    inn = (p.get("inn") or "").strip()
    if not inn:
        return _merge_enrich(p, fssp={"error": "no_inn"})
    report = fetch_fssp(inn)
    _sleep(pause)
    old = dict((p.get("enrich") or {}).get("checklist") or {})
    return _merge_enrich(
        p,
        fssp=report.to_dict(),
        checklist=_checklist_fill_gaps(old, checklist_from_fssp(report)),
    )


def _ogrn_of(p: dict[str, Any]) -> str:
    ogrn = (p.get("ogrn") or "").strip()
    if ogrn:
        return ogrn
    return str(((p.get("enrich") or {}).get("egrul") or {}).get("ogrn") or "").strip()


def apply_companium(payload: dict[str, Any], pause: float = 1.0) -> dict[str, Any]:
    """P/L/I (+V soft) через companium.ru по ОГРН."""
    p = dict(payload)
    ogrn = _ogrn_of(p)
    if ogrn:
        p["ogrn"] = ogrn
    inn = (p.get("inn") or "").strip()
    if not ogrn:
        return _merge_enrich(p, companium={"error": "no_ogrn"})

    report = fetch_companium(ogrn=ogrn, inn=inn)
    _sleep(pause)
    old = dict((p.get("enrich") or {}).get("checklist") or {})
    return _merge_enrich(
        p,
        companium=report.to_dict(),
        checklist=_checklist_fill_gaps(old, checklist_from_companium(report)),
    )


def apply_checko(payload: dict[str, Any], pause: float = 1.0) -> dict[str, Any]:
    """Запасной P/L/I/V через checko.ru (только дыры)."""
    p = dict(payload)
    ogrn = _ogrn_of(p)
    if ogrn:
        p["ogrn"] = ogrn
    inn = (p.get("inn") or "").strip()
    if not ogrn:
        return _merge_enrich(p, checko={"error": "no_ogrn"})

    report = fetch_checko(ogrn=ogrn, inn=inn)
    _sleep(pause)
    old = dict((p.get("enrich") or {}).get("checklist") or {})
    return _merge_enrich(
        p,
        checko=report.to_dict(),
        checklist=_checklist_fill_gaps(old, checklist_from_checko(report)),
    )


def apply_saby(payload: dict[str, Any], pause: float = 1.0) -> dict[str, Any]:
    """Запасной I через saby.ru/profile/{inn}."""
    p = dict(payload)
    inn = (p.get("inn") or "").strip()
    if not inn:
        return _merge_enrich(p, saby={"error": "no_inn"})
    report = fetch_saby(inn)
    _sleep(pause)
    old = dict((p.get("enrich") or {}).get("checklist") or {})
    return _merge_enrich(
        p,
        saby=report.to_dict(),
        checklist=_checklist_fill_gaps(old, checklist_from_saby(report)),
    )


def apply_fedresurs(payload: dict[str, Any], pause: float = 1.0) -> dict[str, Any]:
    """O (банкрот/дисквал) + V (лизинг) через Федресурс + мягкий дисквал ФНС."""
    p = dict(payload)
    inn = (p.get("inn") or "").strip()
    if not inn:
        return _merge_enrich(p, fedresurs={"error": "no_inn"})

    report = fetch_fedresurs(inn)
    checklist = checklist_from_fedresurs(report)

    director = ""
    enrich = p.get("enrich") or {}
    cl0 = enrich.get("checklist") or {}
    director = str(cl0.get("F_director") or (enrich.get("egrul") or {}).get("director") or "")
    found, note = fetch_disqualified(director)
    checklist = merge_o_disqualified(checklist, note, found)

    _sleep(pause)
    old = dict(cl0)
    return _merge_enrich(
        p,
        fedresurs=report.to_dict(),
        disqualified={"found": found, "note": note, "director": director},
        checklist=_checklist_fill_gaps(old, checklist),
    )


def apply_unreliable(payload: dict[str, Any], pause: float = 0.0) -> dict[str, Any]:
    """I по уже сохранённому ЕГРЮЛ (без сети) — только если I ещё пустой."""
    p = dict(payload)
    egrul = (p.get("enrich") or {}).get("egrul") or {}
    report = check_unreliable_from_egrul(egrul)
    if pause:
        _sleep(pause)
    old = dict((p.get("enrich") or {}).get("checklist") or {})
    return _merge_enrich(
        p,
        unreliable=report.to_dict(),
        checklist=_checklist_fill_gaps(old, checklist_from_unreliable(report)),
    )


def rescore_db(db: ListingDB) -> dict[str, int]:
    """Пересчёт M/N/I/status, подписи O/L/P/V, история продажи и полный вердикт."""
    from parser.dedup import annotate_listing_history

    fixed = 0
    payloads = annotate_listing_history(db.all_payloads())
    for p in payloads:
        enrich = p.get("enrich") or {}
        egrul = enrich.get("egrul") or {}
        cl = _remap_checklist_labels(dict(enrich.get("checklist") or {}))
        # имя/ИНН из уже сохранённого ЕГРЮЛ (перебить «с историей…»)
        if egrul.get("name") and not egrul.get("error"):
            official = str(egrul["name"])
            if not official.upper().startswith("ООО"):
                official = f"ООО «{official}»"
            p["name"] = official
        if egrul.get("inn") and not (p.get("inn") or "").strip():
            p["inn"] = str(egrul["inn"])
        if egrul.get("inn") and not egrul.get("error"):
            flags = status_flags(egrul.get("status") or "")
            cl["M_not_liquidating"] = flags["M"]
            cl["N_not_excluding"] = flags["N"]
            cl["status"] = flags["status"]
            cl.update(checklist_from_unreliable(check_unreliable_from_egrul(egrul)))
            if str(egrul.get("status") or "") in {"1", "0", "-"}:
                egrul = dict(egrul)
                egrul["status"] = "действующая"
            p = _merge_enrich(p, egrul=egrul, checklist=cl)
        else:
            p = _merge_enrich(p, checklist=cl) if cl else p
            p["scoring"] = score_payload(p)
        fixed += 1
        db.save_payload(p)
    return {"rescored": fixed, "total": len(payloads)}


def _run_source(
    *,
    name: str,
    payloads: list[dict[str, Any]],
    limit: int,
    pause: float,
    db: ListingDB,
    stats: dict[str, int],
    pick: Callable[[dict[str, Any]], bool],
    apply: Callable[[dict[str, Any], float], dict[str, Any]],
    ok_key: str,
    err_key: str,
    summary: Callable[[dict[str, Any]], str],
) -> None:
    picked = [p for p in payloads if pick(p)]
    # limit<=0 — без потолка (все дыры за один проход источника)
    candidates = picked if limit <= 0 else picked[:limit]
    print(f"{name}: {len(candidates)} шт" + ("" if limit <= 0 else f" (лимит {limit})"))

    captcha_streak = 0
    for i, p in enumerate(candidates, 1):
        key = p.get("inn") or p.get("ogrn") or p.get("name")
        print(f"  [{name} {i}/{len(candidates)}] {key} ...", end=" ", flush=True)
        updated = apply(p, pause)
        stats["attempted"] += 1
        enrich_u = updated.get("enrich") or {}
        if apply is apply_egrul:
            src_block = enrich_u.get("egrul") or {}
        elif apply is apply_buh:
            src_block = enrich_u.get("buh") or {}
        elif apply is apply_kad:
            src_block = enrich_u.get("kad") or {}
        elif apply is apply_fssp:
            src_block = enrich_u.get("fssp") or {}
        elif apply is apply_fedresurs:
            src_block = enrich_u.get("fedresurs") or {}
        elif apply is apply_companium:
            src_block = enrich_u.get("companium") or {}
        elif apply is apply_checko:
            src_block = enrich_u.get("checko") or {}
        elif apply is apply_saby:
            src_block = enrich_u.get("saby") or {}
        else:
            src_block = enrich_u.get("unreliable") or {}

        err = str(src_block.get("error") or "")
        soft_ok = apply in (
            apply_kad,
            apply_fssp,
            apply_fedresurs,
            apply_unreliable,
            apply_companium,
            apply_checko,
            apply_saby,
        )
        if err and not soft_ok:
            stats[err_key] += 1
            print(f"ERR {err}")
            db.save_payload(updated)
            if err == "captcha" and apply is apply_egrul:
                print("Капча ЕГРЮЛ — стоп.")
                raise StopIteration
            continue

        stats[ok_key] += 1
        prefix = "SOFT" if err else "OK"
        print(prefix, summary(updated))
        db.save_payload(updated)

        # Companium/Checko: много фирм подряд только капча → пул сдох, стоп источника.
        # Порог выше: одна фирма уже крутит десятки прокси, 3 подряд — слишком рано.
        if apply in (apply_companium, apply_checko) and (
            "recaptcha" in err.lower()
            or "captcha" in err.lower()
            or "proxy" in err.lower()
            or "407" in err
            or err in {"429", "http_429", "proxy_exhausted"}
        ):
            captcha_streak += 1
            if captcha_streak >= 12:
                print(
                    f"  → {name}: капча/прокси {captcha_streak}× фирм подряд — стоп. "
                    "Проверьте whitelist IP или ENRICH_PROXY_LIST_URL."
                )
                break
        else:
            captcha_streak = 0


def enrich_db(
    db: ListingDB,
    *,
    limit: int = 40,
    only_with_key: bool = True,
    pause: float | None = None,
    unique_first: bool = True,
    sources: list[str] | None = None,
) -> dict[str, int]:
    from parser.dedup import unique_only

    if pause is None:
        pause = ENRICH_PAUSE

    sources = sources or [
        "egrul",
        "buh",
        "companium",
        "checko",
        "fedresurs",
        "saby",
        "unreliable",
    ]
    payloads = unique_only(db.all_payloads()) if unique_first else db.all_payloads()

    stats = {
        "egrul_ok": 0,
        "egrul_err": 0,
        "buh_ok": 0,
        "buh_err": 0,
        "kad_ok": 0,
        "kad_err": 0,
        "fssp_ok": 0,
        "fssp_err": 0,
        "companium_ok": 0,
        "companium_err": 0,
        "checko_ok": 0,
        "checko_err": 0,
        "fedresurs_ok": 0,
        "fedresurs_err": 0,
        "saby_ok": 0,
        "saby_err": 0,
        "unreliable_ok": 0,
        "unreliable_err": 0,
        "attempted": 0,
    }

    print(
        f"Паузы: base={pause}s + jitter=0..{ENRICH_JITTER}s "
        f"(~{pause:.0f}–{pause + ENRICH_JITTER:.0f}s между запросами)"
    )
    try:
        from parser.enrich.proxy_pool import ensure_loaded, proxy_enabled

        if proxy_enabled():
            n = ensure_loaded()
            print(f"Прокси-пул (Companium/Checko): {n} шт из списка/кэша")
    except Exception as e:  # noqa: BLE001
        print(f"Прокси-пул: не загрузился ({e})")

    try:
        if "egrul" in sources:

            def _pick_egrul(p: dict[str, Any]) -> bool:
                if only_with_key and not (p.get("inn") or p.get("ogrn")):
                    return False
                eg = (p.get("enrich") or {}).get("egrul") or {}
                return not (eg.get("inn") and not eg.get("error"))

            _run_source(
                name="ЕГРЮЛ",
                payloads=payloads,
                limit=limit,
                pause=pause,
                db=db,
                stats=stats,
                pick=_pick_egrul,
                apply=apply_egrul,
                ok_key="egrul_ok",
                err_key="egrul_err",
                summary=lambda u: f"inn={(u.get('enrich') or {}).get('egrul', {}).get('inn')} "
                f"status={(u.get('enrich') or {}).get('checklist', {}).get('status')}",
            )
            payloads = unique_only(db.all_payloads()) if unique_first else db.all_payloads()

        if "buh" in sources:
            _run_source(
                name="БФО",
                payloads=payloads,
                limit=limit,
                pause=pause,
                db=db,
                stats=stats,
                pick=lambda p: bool(p.get("inn"))
                and not (
                    ((p.get("enrich") or {}).get("buh") or {}).get("years")
                    and not ((p.get("enrich") or {}).get("buh") or {}).get("error")
                ),
                apply=apply_buh,
                ok_key="buh_ok",
                err_key="buh_err",
                summary=lambda u: (
                    f"R={(u.get('enrich') or {}).get('checklist', {}).get('R_turnover')} "
                    f"U={(u.get('enrich') or {}).get('checklist', {}).get('U_reports_filed')}"
                ),
            )
            payloads = unique_only(db.all_payloads()) if unique_first else db.all_payloads()

        if "companium" in sources:
            def _pick_companium(p: dict[str, Any]) -> bool:
                ogrn = (p.get("ogrn") or "").strip() or str(
                    ((p.get("enrich") or {}).get("egrul") or {}).get("ogrn") or ""
                )
                if not ogrn:
                    return False
                cl = (p.get("enrich") or {}).get("checklist") or {}
                # пока P/L не стали осмысленными (или ещё ПРОВЕРИТЬ от КАД/ФССП)
                p_ok = cl.get("P_court_cases") in ("есть дела", "нет дел", "ЕСТЬ", "НЕТ")
                l_ok = cl.get("L_debts_il") in (
                    "нет долгов/ИЛ",
                    "есть долги/ИЛ",
                    "ДА",
                    "НЕТ",
                )
                # если уже от companium — не долбим
                src = ((p.get("enrich") or {}).get("companium") or {})
                if src.get("ogrn") and not src.get("error") and p_ok and l_ok:
                    return False
                return not (p_ok and l_ok)

            _run_source(
                name="Companium",
                payloads=payloads,
                limit=limit,
                pause=pause,
                db=db,
                stats=stats,
                pick=_pick_companium,
                apply=apply_companium,
                ok_key="companium_ok",
                err_key="companium_err",
                summary=lambda u: (
                    ((u.get("enrich") or {}).get("checklist") or {}).get("dossier")
                    or (
                        f"суды={(u.get('enrich') or {}).get('checklist', {}).get('P_court_cases')} "
                        f"долги={(u.get('enrich') or {}).get('checklist', {}).get('L_debts_il')}"
                    )
                ),
            )
            payloads = unique_only(db.all_payloads()) if unique_first else db.all_payloads()

        if "checko" in sources:

            def _pick_checko(p: dict[str, Any]) -> bool:
                if not _ogrn_of(p):
                    return False
                cl = (p.get("enrich") or {}).get("checklist") or {}
                # только P/L/I — V добивает Федресурс, не жжём Checko зря
                return (
                    _is_gap(cl.get("P_court_cases"))
                    or _is_gap(cl.get("L_debts_il"))
                    or _is_gap(cl.get("I_reliable"))
                )

            _run_source(
                name="Checko",
                payloads=payloads,
                limit=limit,
                pause=pause,
                db=db,
                stats=stats,
                pick=_pick_checko,
                apply=apply_checko,
                ok_key="checko_ok",
                err_key="checko_err",
                summary=lambda u: (
                    f"P={(u.get('enrich') or {}).get('checklist', {}).get('P_court_cases')} "
                    f"L={(u.get('enrich') or {}).get('checklist', {}).get('L_debts_il')}"
                ),
            )
            payloads = unique_only(db.all_payloads()) if unique_first else db.all_payloads()

        if "kad" in sources:
            def _pick_kad(p: dict[str, Any]) -> bool:
                if not p.get("inn"):
                    return False
                cl = (p.get("enrich") or {}).get("checklist") or {}
                # повторяем, пока нет жёсткого ответа (ПРОВЕРИТЬ / пусто)
                return cl.get("P_court_cases") not in ("ЕСТЬ", "НЕТ", "есть дела", "нет дел")

            _run_source(
                name="КАД",
                payloads=payloads,
                limit=limit,
                pause=pause,
                db=db,
                stats=stats,
                pick=_pick_kad,
                apply=apply_kad,
                ok_key="kad_ok",
                err_key="kad_err",
                summary=lambda u: (
                    f"P={(u.get('enrich') or {}).get('checklist', {}).get('P_court_cases')} "
                    f"src={((u.get('enrich') or {}).get('kad') or {}).get('source', '')[:40]}"
                ),
            )
            payloads = unique_only(db.all_payloads()) if unique_first else db.all_payloads()

        if "fssp" in sources:
            _run_source(
                name="ФССП",
                payloads=payloads,
                limit=limit,
                pause=pause,
                db=db,
                stats=stats,
                pick=lambda p: bool(p.get("inn"))
                and "L_debts_il" not in ((p.get("enrich") or {}).get("checklist") or {}),
                apply=apply_fssp,
                ok_key="fssp_ok",
                err_key="fssp_err",
                summary=lambda u: f"L={(u.get('enrich') or {}).get('checklist', {}).get('L_debts_il')}",
            )
            payloads = unique_only(db.all_payloads()) if unique_first else db.all_payloads()

        if "fedresurs" in sources:
            _run_source(
                name="Федресурс",
                payloads=payloads,
                limit=limit,
                pause=pause,
                db=db,
                stats=stats,
                pick=lambda p: bool(p.get("inn"))
                and _flag_o_needs_retry((p.get("enrich") or {}).get("checklist") or {}),
                apply=apply_fedresurs,
                ok_key="fedresurs_ok",
                err_key="fedresurs_err",
                summary=lambda u: (
                    f"O={(u.get('enrich') or {}).get('checklist', {}).get('O_clean')} "
                    f"V={(u.get('enrich') or {}).get('checklist', {}).get('V_leases')}"
                ),
            )
            payloads = unique_only(db.all_payloads()) if unique_first else db.all_payloads()

        if "saby" in sources:
            _run_source(
                name="Saby",
                payloads=payloads,
                limit=limit,
                pause=pause,
                db=db,
                stats=stats,
                pick=lambda p: bool(p.get("inn"))
                and _is_gap(((p.get("enrich") or {}).get("checklist") or {}).get("I_reliable")),
                apply=apply_saby,
                ok_key="saby_ok",
                err_key="saby_err",
                summary=lambda u: f"I={(u.get('enrich') or {}).get('checklist', {}).get('I_reliable')}",
            )
            payloads = unique_only(db.all_payloads()) if unique_first else db.all_payloads()

        if "unreliable" in sources:
            _run_source(
                name="Недостоверки",
                payloads=payloads,
                limit=limit,
                pause=0.0,
                db=db,
                stats=stats,
                pick=lambda p: bool(((p.get("enrich") or {}).get("egrul") or {}).get("inn"))
                and _is_gap(((p.get("enrich") or {}).get("checklist") or {}).get("I_reliable")),
                apply=apply_unreliable,
                ok_key="unreliable_ok",
                err_key="unreliable_err",
                summary=lambda u: f"I={(u.get('enrich') or {}).get('checklist', {}).get('I_reliable')}",
            )
    except StopIteration:
        pass

    return stats
