from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime
from typing import Any


def _norm_name(name: str) -> str:
    s = (name or "").upper()
    s = s.replace("Ё", "Е")
    s = re.sub(r"^ООО\s*", "", s)
    s = re.sub(r"[«»\"'“”.,]", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _dedupe_key(p: dict[str, Any]) -> str:
    inn = (p.get("inn") or "").strip()
    if inn and inn.isdigit() and len(inn) == 10:
        return f"inn:{inn}"
    ogrn = (p.get("ogrn") or "").strip()
    if ogrn and ogrn.isdigit() and len(ogrn) == 13:
        return f"ogrn:{ogrn}"
    name = _norm_name(p.get("name") or "")
    price = p.get("price_rub") or 0
    if name and price:
        return f"np:{name}|{price}"
    if name:
        return f"n:{name}"
    return f"msg:{p.get('chat_id')}:{p.get('message_id')}:{p.get('block_index')}"


def _parse_dt(raw: str) -> datetime | None:
    s = (raw or "").strip()
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None


def annotate_listing_history(payloads: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Сколько раз лот светился в чате и как давно продают (по msg_date)."""
    by_key: dict[str, list[str]] = defaultdict(list)
    for p in payloads:
        by_key[_dedupe_key(p)].append(p.get("msg_date") or "")

    out: list[dict[str, Any]] = []
    for p in payloads:
        q = dict(p)
        key = _dedupe_key(p)
        dates_raw = [d for d in by_key.get(key, []) if d]
        parsed = sorted(d for d in (_parse_dt(x) for x in dates_raw) if d is not None)
        q["listing_count"] = max(1, len(by_key.get(key, []) or [1]))
        if parsed:
            first, last = parsed[0], parsed[-1]
            q["listing_first_seen"] = first.isoformat()
            q["listing_last_seen"] = last.isoformat()
            q["listing_days"] = max(0, (last - first).days)
        else:
            q["listing_first_seen"] = ""
            q["listing_last_seen"] = ""
            q["listing_days"] = 0
        out.append(q)
    return out


def mark_duplicates(payloads: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Оставляет лучший лот в группе (выше score, свежее сообщение).
    Остальным ставит is_duplicate=True.
    """
    from config import INN_CHAT_IDS

    inn_chats = {int(x) for x in INN_CHAT_IDS}
    payloads = annotate_listing_history(payloads)
    best_idx: dict[str, int] = {}
    scores: list[tuple[int, int, str, int]] = []
    for i, p in enumerate(payloads):
        sc = int((p.get("scoring") or {}).get("score") or 0)
        # при равном score предпочитаем объявление из группы продаж, не очередь ИНН
        prefer_sales = 0 if int(p.get("chat_id") or 0) in inn_chats else 1
        dt = p.get("msg_date") or ""
        scores.append((sc, prefer_sales, dt, i))

    # score → группа продаж → более новая дата
    order = sorted(
        range(len(payloads)),
        key=lambda i: (scores[i][0], scores[i][1], scores[i][2]),
        reverse=True,
    )

    seen: set[str] = set()
    keep: set[int] = set()
    for i in order:
        key = _dedupe_key(payloads[i])
        if key in seen:
            continue
        seen.add(key)
        keep.add(i)
        best_idx[key] = i

    out: list[dict[str, Any]] = []
    for i, p in enumerate(payloads):
        q = dict(p)
        if i in keep:
            q["is_duplicate"] = False
            q["duplicate_of"] = ""
        else:
            key = _dedupe_key(p)
            q["is_duplicate"] = True
            bi = best_idx.get(key)
            if bi is not None:
                q["duplicate_of"] = payloads[bi].get("link") or ""
            else:
                q["duplicate_of"] = ""
        out.append(q)
    return out


def unique_only(payloads: list[dict[str, Any]]) -> list[dict[str, Any]]:
    marked = mark_duplicates(payloads)
    return [p for p in marked if not p.get("is_duplicate")]
