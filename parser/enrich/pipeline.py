from __future__ import annotations

import random
import re
import time
from datetime import datetime, timezone
from typing import Any

from config import ENRICH_JITTER, ENRICH_PAUSE
from parser.db import ListingDB
from parser.score import score_payload

from .buh import checklist_from_buh, fetch_buh
from .egrul import lookup_company, status_flags


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sleep(pause: float | None = None) -> float:
    """Пауза + джиттер, чтобы не капчило."""
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
    checklist = {
        "F_address": rec.address,
        "F_director": rec.director,
        "C_reg_date": rec.reg_date,
        "M_not_liquidating": flags["M"],
        "N_not_excluding": flags["N"],
        "status": flags["status"],
        "kpp": rec.kpp,
    }
    return _merge_enrich(p, egrul=rec.to_dict(), checklist=checklist)


def apply_buh(payload: dict[str, Any], pause: float = 1.0) -> dict[str, Any]:
    p = dict(payload)
    inn = (p.get("inn") or "").strip()
    if not inn:
        return _merge_enrich(p, buh={"error": "no_inn"})

    # внутренние паузы fetch_buh оставляем короткими; основная — между лотами
    report = fetch_buh(inn, pause=min(pause, 2.0) if pause else 1.0)
    _sleep(pause)
    if report.error:
        return _merge_enrich(p, buh=report.to_dict())

    cl = checklist_from_buh(report)
    # подмешиваем официальные обороты в payload для скоринга
    if cl.get("revenues"):
        # не затираем текстовые из TG полностью — кладём отдельно, score читает buh
        pass
    return _merge_enrich(p, buh=report.to_dict(), checklist=cl)


def enrich_db(
    db: ListingDB,
    *,
    limit: int = 40,
    only_with_key: bool = True,
    pause: float | None = None,
    unique_first: bool = True,
    sources: list[str] | None = None,
) -> dict[str, int]:
    """
    sources: egrul, buh (по умолчанию оба, если передано явно — только они)
    pause=None → берём ENRICH_PAUSE из config/.env (+ джиттер)
    """
    from parser.dedup import unique_only

    if pause is None:
        pause = ENRICH_PAUSE

    sources = sources or ["egrul", "buh"]
    payloads = db.all_payloads()
    if unique_first:
        payloads = unique_only(payloads)

    stats = {
        "egrul_ok": 0,
        "egrul_err": 0,
        "buh_ok": 0,
        "buh_err": 0,
        "attempted": 0,
    }

    print(
        f"Паузы: base={pause}s + jitter=0..{ENRICH_JITTER}s "
        f"(~{pause:.0f}–{pause + ENRICH_JITTER:.0f}s между запросами)"
    )

    # --- ЕГРЮЛ ---
    if "egrul" in sources:
        candidates: list[dict[str, Any]] = []
        for p in payloads:
            enrich = p.get("enrich") or {}
            egrul = enrich.get("egrul") or {}
            if egrul.get("inn") and not egrul.get("error"):
                continue
            if only_with_key and not (p.get("inn") or p.get("ogrn")):
                continue
            candidates.append(p)
        candidates = candidates[:limit]
        print(f"ЕГРЮЛ: {len(candidates)} шт")
        for i, p in enumerate(candidates, 1):
            key = p.get("inn") or p.get("ogrn") or p.get("name")
            print(f"  [egrul {i}/{len(candidates)}] {key} ...", end=" ", flush=True)
            updated = apply_egrul(p, pause=pause)
            egrul = (updated.get("enrich") or {}).get("egrul") or {}
            stats["attempted"] += 1
            if egrul.get("error"):
                stats["egrul_err"] += 1
                print(f"ERR {egrul.get('error')}")
                db.save_payload(updated)
                if egrul.get("error") == "captcha":
                    print("Капча ЕГРЮЛ — стоп. Увеличь ENRICH_PAUSE и повтори позже.")
                    break
            else:
                stats["egrul_ok"] += 1
                print(f"OK inn={egrul.get('inn')} status={egrul.get('status')}")
                db.save_payload(updated)
            payloads = unique_only(db.all_payloads()) if unique_first else db.all_payloads()

    # --- БФО ---
    if "buh" in sources:
        payloads = unique_only(db.all_payloads()) if unique_first else db.all_payloads()
        candidates = []
        for p in payloads:
            if not p.get("inn"):
                continue
            buh = (p.get("enrich") or {}).get("buh") or {}
            if buh.get("years") and not buh.get("error"):
                continue
            candidates.append(p)
        candidates = candidates[:limit]
        print(f"БФО: {len(candidates)} шт")
        for i, p in enumerate(candidates, 1):
            inn = p.get("inn")
            print(f"  [buh {i}/{len(candidates)}] {inn} ...", end=" ", flush=True)
            updated = apply_buh(p, pause=pause)
            buh = (updated.get("enrich") or {}).get("buh") or {}
            stats["attempted"] += 1
            if buh.get("error"):
                stats["buh_err"] += 1
                print(f"ERR {buh.get('error')}")
            else:
                stats["buh_ok"] += 1
                cl = (updated.get("enrich") or {}).get("checklist") or {}
                print(
                    f"OK R={cl.get('R_turnover')} U={cl.get('U_reports_filed')} "
                    f"yrs={len(buh.get('years') or [])}"
                )
            db.save_payload(updated)

    return stats
