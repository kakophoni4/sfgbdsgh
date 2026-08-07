from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, dataclass
from typing import Any

BASE = "https://egrul.nalog.ru"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)


@dataclass
class EgrulRecord:
    name: str = ""
    name_full: str = ""
    inn: str = ""
    ogrn: str = ""
    kpp: str = ""
    address: str = ""
    director: str = ""
    status: str = ""
    reg_date: str = ""
    okved: str = ""
    kind: str = ""
    raw: dict[str, Any] | None = None
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _session():
    """Предпочитаем curl_cffi (Chrome TLS), иначе requests."""
    try:
        from curl_cffi import requests as crequests  # type: ignore

        s = crequests.Session()
        s.headers.update(
            {
                "User-Agent": UA,
                "Accept": "application/json, text/javascript, */*; q=0.01",
                "X-Requested-With": "XMLHttpRequest",
                "Referer": f"{BASE}/index.html",
            }
        )
        s._impersonate = "chrome124"  # type: ignore[attr-defined]
        s._engine = "curl_cffi"
        return s
    except Exception:
        import requests

        s = requests.Session()
        s.headers.update(
            {
                "User-Agent": UA,
                "Accept": "application/json, text/javascript, */*; q=0.01",
                "X-Requested-With": "XMLHttpRequest",
                "Referer": f"{BASE}/index.html",
            }
        )
        s._engine = "requests"  # type: ignore[attr-defined]
        return s


def _post(session, url: str, data: dict) -> dict:
    kwargs = {"data": data, "timeout": 30}
    if getattr(session, "_engine", "") == "curl_cffi":
        kwargs["impersonate"] = getattr(session, "_impersonate", "chrome124")
    r = session.post(url, **kwargs)
    r.raise_for_status()
    return r.json()


def _get(session, url: str) -> dict:
    kwargs = {"timeout": 30}
    if getattr(session, "_engine", "") == "curl_cffi":
        kwargs["impersonate"] = getattr(session, "_impersonate", "chrome124")
    r = session.get(url, **kwargs)
    r.raise_for_status()
    return r.json()


def _row_to_record(row: dict[str, Any]) -> EgrulRecord:
    # e — часто пусто у действующих; иногда дата прекращения (не путать со статусом-текстом)
    raw_e = (row.get("e") or "").strip()
    if not raw_e or raw_e in {"1", "0", "-"}:
        status = "действующая"
    elif re.fullmatch(r"\d{1,2}[./]\d{1,2}[./]\d{2,4}", raw_e):
        status = f"прекращена {raw_e}"
    else:
        status = raw_e
    return EgrulRecord(
        name=(row.get("c") or row.get("n") or "").strip(),
        name_full=(row.get("n") or "").strip(),
        inn=(row.get("i") or "").strip(),
        ogrn=(row.get("o") or "").strip(),
        kpp=(row.get("p") or "").strip(),
        address=(row.get("a") or "").strip(),
        director=(row.get("g") or "").strip(),
        status=status,
        reg_date=(row.get("r") or "").strip(),
        okved=(row.get("okved") or row.get("ok") or "").strip(),
        kind=(row.get("k") or "").strip(),
        raw=row,
    )


def search_egrul(query: str, *, retries: int = 2) -> list[EgrulRecord]:
    query = (query or "").strip()
    if not query:
        return []

    last_err = ""
    for attempt in range(retries + 1):
        try:
            session = _session()
            token_resp = _post(
                session,
                f"{BASE}/",
                {
                    "query": query,
                    "vyp3CaptchaToken": "",
                    "page": "",
                    "region": "",
                    "PreventChromeAutocomplete": "",
                },
            )
            if token_resp.get("captchaRequired") or token_resp.get("captcha"):
                return [EgrulRecord(error="captcha")]
            token = token_resp.get("t")
            if not token:
                return [EgrulRecord(error=f"no_token:{json.dumps(token_resp, ensure_ascii=False)[:200]}")]

            rows: list[dict] = []
            for _ in range(15):
                res = _get(session, f"{BASE}/search-result/{token}")
                rows = res.get("rows") or []
                if rows:
                    break
                time.sleep(0.5)
            return [_row_to_record(r) for r in rows]
        except Exception as e:  # noqa: BLE001
            last_err = str(e)
            time.sleep(1.2 * (attempt + 1))
    return [EgrulRecord(error=last_err or "unknown")]


def _year_of(reg_date: str) -> int | None:
    s = (reg_date or "").strip()
    if not s:
        return None
    # 13.12.2024 / 2024-12-13 / 2024
    for part in (s[-4:], s[:4]):
        if part.isdigit() and 1990 <= int(part) <= 2100:
            return int(part)
    m = re.search(r"(20\d{2}|19\d{2})", s)
    return int(m.group(1)) if m else None


def _name_query(name: str) -> str:
    """Нормализация для поиска: ООО «Векта+» → ООО Векта+."""
    s = (name or "").strip()
    s = re.sub(r"[«»\"“”']", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _norm_brand(s: str) -> str:
    t = (s or "").upper().replace("Ё", "Е")
    t = re.sub(r"(?i)^ООО\s*", "", t)
    t = re.sub(r"[«»\"“”'.,\-—+]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def _name_similar(query: str, candidate: str) -> bool:
    """Не принимать чужой хит ЕГРЮЛ на запрос «Для связи @…» / частичное совпадение."""
    a = _norm_brand(query)
    b = _norm_brand(candidate)
    if not a or not b:
        return False
    if a == b:
        return True
    # бренд запроса целиком входит в ответ или наоборот (ООО ВЕКТА / ВЕКТА ПЛЮС)
    if len(a) >= 4 and (a in b or b in a):
        return True
    # все слова запроса (от 3 букв) есть в ответе
    words = [w for w in a.split() if len(w) >= 3]
    if words and all(w in b for w in words):
        return True
    return False


def lookup_company(
    *,
    inn: str = "",
    ogrn: str = "",
    name: str = "",
    reg_year: int | None = None,
) -> EgrulRecord:
    """ИНН/ОГРН — точно. Имя — только похожий хит + год (если есть)."""
    for q, kind in ((inn, "inn"), (ogrn, "ogrn"), (name, "name")):
        q = (q or "").strip()
        if not q:
            continue
        if kind == "name":
            q = _name_query(q)
            if len(q) < 5:
                continue
        rows = search_egrul(q)
        if not rows:
            continue
        if rows[0].error:
            return rows[0]
        if kind == "inn":
            for r in rows:
                if r.inn == q:
                    return r
            continue
        if kind == "ogrn":
            for r in rows:
                if r.ogrn == q:
                    return r
            continue
        # --- поиск по имени: только строки с похожим названием ---
        similar = [
            r
            for r in rows
            if _name_similar(q, r.name) or _name_similar(q, r.name_full)
        ]
        if not similar:
            return EgrulRecord(error=f"name_no_similar:{len(rows)}", name=q)

        pool = similar
        if reg_year:
            by_year = [r for r in similar if _year_of(r.reg_date) == int(reg_year)]
            if len(by_year) == 1:
                return by_year[0]
            if len(by_year) > 1:
                return EgrulRecord(
                    error=f"ambiguous_name_year:{len(by_year)}",
                    name=q,
                )
            # год не совпал среди похожих
            if len(similar) == 1:
                return similar[0]
            return EgrulRecord(
                error=f"name_year_mismatch:{len(similar)}",
                name=q,
            )
        if len(pool) == 1:
            return pool[0]
        return EgrulRecord(error=f"ambiguous_name:{len(pool)}", name=q)
    return EgrulRecord(error="empty_query")


def status_flags(status: str) -> dict[str, str]:
    s = (status or "").lower().strip()
    liquid_markers = ("ликвидац", "в процессе ликвидации", "ликвидиров")
    # прекращена / исключена / недействующая — мёртвая для покупки
    dead_markers = (
        "прекращ",
        "исключ",
        "недействующ",
        "аннулир",
        "реорганизац",
        "снят с учета",
        "снята с учета",
    )

    on_liquid = any(m in s for m in liquid_markers)
    on_dead = any(m in s for m in dead_markers)

    if not s or s in {"1", "0", "-"}:
        return {"M": "ДА", "N": "ДА", "status": "действующая"}
    # «действующая» без маркеров смерти
    if "действующ" in s and not on_liquid and not on_dead:
        return {"M": "ДА", "N": "ДА", "status": status}

    return {
        "M": "НЕТ" if (on_liquid or on_dead) else "ДА",
        "N": "НЕТ" if on_dead else "ДА",
        "status": status,
    }
