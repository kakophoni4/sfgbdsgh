from __future__ import annotations

import re
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


def mark_duplicates(payloads: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Оставляет лучший лот в группе (выше score, свежее сообщение).
    Остальным ставит is_duplicate=True.
    """
    best_idx: dict[str, int] = {}
    scores: list[tuple[int, str, int]] = []
    for i, p in enumerate(payloads):
        sc = int((p.get("scoring") or {}).get("score") or 0)
        dt = p.get("msg_date") or ""
        scores.append((sc, dt, i))

    # сначала более высокий score, потом более новая дата
    order = sorted(range(len(payloads)), key=lambda i: (scores[i][0], scores[i][1]), reverse=True)

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
