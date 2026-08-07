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
from .egrul import lookup_company, status_flags
from .fedresurs import (
    checklist_from_fedresurs,
    fetch_disqualified,
    fetch_fedresurs,
    merge_o_disqualified,
)
from .fssp import checklist_from_fssp, fetch_fssp
from .kad import checklist_from_kad, fetch_kad
from .unreliable import check_unreliable_from_egrul, checklist_from_unreliable


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


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
    if rec.name and (not p.get("name") or len(p.get("name") or "") < 5):
        p["name"] = rec.name if rec.name.upper().startswith("ООО") else f"ООО «{rec.name}»"
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
    return _merge_enrich(p, kad=report.to_dict(), checklist=checklist_from_kad(report))


def apply_fssp(payload: dict[str, Any], pause: float = 1.0) -> dict[str, Any]:
    p = dict(payload)
    inn = (p.get("inn") or "").strip()
    if not inn:
        return _merge_enrich(p, fssp={"error": "no_inn"})
    report = fetch_fssp(inn)
    _sleep(pause)
    return _merge_enrich(p, fssp=report.to_dict(), checklist=checklist_from_fssp(report))


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
    return _merge_enrich(
        p,
        fedresurs=report.to_dict(),
        disqualified={"found": found, "note": note, "director": director},
        checklist=checklist,
    )


def apply_unreliable(payload: dict[str, Any], pause: float = 0.0) -> dict[str, Any]:
    """I по уже сохранённому ЕГРЮЛ (без сети, если карточка есть)."""
    p = dict(payload)
    egrul = (p.get("enrich") or {}).get("egrul") or {}
    report = check_unreliable_from_egrul(egrul)
    if pause:
        _sleep(pause)
    return _merge_enrich(
        p,
        unreliable=report.to_dict(),
        checklist=checklist_from_unreliable(report),
    )


def rescore_db(db: ListingDB) -> dict[str, int]:
    """Пересчёт M/N/I/status и score по уже сохранённым enrich (без сети)."""
    fixed = 0
    for p in db.all_payloads():
        enrich = p.get("enrich") or {}
        egrul = enrich.get("egrul") or {}
        if egrul.get("inn") and not egrul.get("error"):
            flags = status_flags(egrul.get("status") or "")
            cl = dict(enrich.get("checklist") or {})
            cl["M_not_liquidating"] = flags["M"]
            cl["N_not_excluding"] = flags["N"]
            cl["status"] = flags["status"]
            cl.update(checklist_from_unreliable(check_unreliable_from_egrul(egrul)))
            # поправить и в egrul.status если был "1"
            if str(egrul.get("status") or "") in {"1", "0", "-"}:
                egrul = dict(egrul)
                egrul["status"] = "действующая"
            p = _merge_enrich(p, egrul=egrul, checklist=cl)
            fixed += 1
        else:
            p["scoring"] = score_payload(p)
        db.save_payload(p)
    return {"rescored": fixed, "total": len(db.all_payloads())}


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
    candidates = [p for p in payloads if pick(p)][:limit]
    print(f"{name}: {len(candidates)} шт")
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
        else:
            src_block = enrich_u.get("unreliable") or {}

        soft_ok = apply in (apply_kad, apply_fssp, apply_fedresurs, apply_unreliable)
        if src_block.get("error") and not soft_ok:
            stats[err_key] += 1
            print(f"ERR {src_block.get('error')}")
            db.save_payload(updated)
            if src_block.get("error") == "captcha" and apply is apply_egrul:
                print("Капча ЕГРЮЛ — стоп.")
                raise StopIteration
            continue

        stats[ok_key] += 1
        prefix = "SOFT" if src_block.get("error") else "OK"
        print(prefix, summary(updated))
        db.save_payload(updated)


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

    sources = sources or ["egrul", "buh", "kad", "fssp", "fedresurs", "unreliable"]
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
        "fedresurs_ok": 0,
        "fedresurs_err": 0,
        "unreliable_ok": 0,
        "unreliable_err": 0,
        "attempted": 0,
    }

    print(
        f"Паузы: base={pause}s + jitter=0..{ENRICH_JITTER}s "
        f"(~{pause:.0f}–{pause + ENRICH_JITTER:.0f}s между запросами)"
    )

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

        if "kad" in sources:
            _run_source(
                name="КАД",
                payloads=payloads,
                limit=limit,
                pause=pause,
                db=db,
                stats=stats,
                pick=lambda p: bool(p.get("inn"))
                and "P_court_cases" not in ((p.get("enrich") or {}).get("checklist") or {}),
                apply=apply_kad,
                ok_key="kad_ok",
                err_key="kad_err",
                summary=lambda u: f"P={(u.get('enrich') or {}).get('checklist', {}).get('P_court_cases')}",
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
                and "O_clean" not in ((p.get("enrich") or {}).get("checklist") or {}),
                apply=apply_fedresurs,
                ok_key="fedresurs_ok",
                err_key="fedresurs_err",
                summary=lambda u: (
                    f"O={(u.get('enrich') or {}).get('checklist', {}).get('O_clean')} "
                    f"V={(u.get('enrich') or {}).get('checklist', {}).get('V_leases')}"
                ),
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
                and "I_reliable" not in ((p.get("enrich") or {}).get("checklist") or {}),
                apply=apply_unreliable,
                ok_key="unreliable_ok",
                err_key="unreliable_err",
                summary=lambda u: f"I={(u.get('enrich') or {}).get('checklist', {}).get('I_reliable')}",
            )
    except StopIteration:
        pass

    return stats
