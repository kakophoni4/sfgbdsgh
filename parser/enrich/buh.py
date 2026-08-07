from __future__ import annotations

import socket
import time
from dataclasses import asdict, dataclass, field
from typing import Any
from urllib.parse import urlparse

from .http_util import http_get, make_session


def _host_ok(host: str) -> bool:
    try:
        socket.gethostbyname(host)
        return True
    except Exception:
        return False


def _bases() -> list[str]:
    """На сервере gov.ru резолвится — берём его первым (туда редиректит bo.nalog.ru)."""
    ordered = []
    if _host_ok("bo.nalog.gov.ru"):
        ordered.append("https://bo.nalog.gov.ru")
    if _host_ok("bo.nalog.ru"):
        ordered.append("https://bo.nalog.ru")
    return ordered or ["https://bo.nalog.gov.ru", "https://bo.nalog.ru"]


@dataclass
class YearFinance:
    period: str = ""
    revenue: int | None = None  # руб, строка 2110
    borrowed_short: int | None = None  # 1510
    borrowed_long: int | None = None  # 1410
    payables: int | None = None  # 1520 кредиторка


@dataclass
class BuhReport:
    inn: str = ""
    org_id: str = ""
    name: str = ""
    years: list[YearFinance] = field(default_factory=list)
    error: str = ""
    source: str = "bo.nalog.gov.ru"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _to_rub(val: Any) -> int | None:
    """В БФО суммы обычно в тыс. руб."""
    if val is None or val == "":
        return None
    try:
        return int(float(val) * 1000)
    except (TypeError, ValueError):
        return None


def _dig(obj: Any, *paths: tuple[str, ...]) -> Any:
    for path in paths:
        cur = obj
        ok = True
        for key in path:
            if not isinstance(cur, dict) or key not in cur:
                ok = False
                break
            cur = cur[key]
        if ok:
            return cur
    return None


def _extract_correction(block: dict[str, Any]) -> dict[str, Any]:
    for key in ("typeCorrections", "corrections", "correctionList"):
        arr = block.get(key)
        if isinstance(arr, list) and arr:
            item = arr[0]
            if isinstance(item, dict):
                if isinstance(item.get("correction"), dict):
                    return item["correction"]
                return item
    if isinstance(block.get("correction"), dict):
        return block["correction"]
    return block


def _parse_year_block(block: dict[str, Any]) -> YearFinance:
    period = str(block.get("period") or block.get("periodName") or "")
    corr = _extract_correction(block)

    fr = corr.get("financialResult") if isinstance(corr.get("financialResult"), dict) else {}
    bal = corr.get("balance") if isinstance(corr.get("balance"), dict) else {}
    if not fr and not bal:
        fr = corr
        bal = corr

    revenue = _to_rub(
        _dig(
            {"fr": fr, "b": block, "c": corr},
            ("fr", "current2110"),
            ("fr", "current_2110"),
            ("c", "current2110"),
            ("b", "gainSum"),
            ("b", "revenue"),
        )
    )
    if revenue is None and block.get("gainSum") is not None:
        revenue = _to_rub(block.get("gainSum"))

    borrowed_short = _to_rub(
        _dig({"bal": bal, "c": corr}, ("bal", "current1510"), ("c", "current1510"))
    )
    borrowed_long = _to_rub(
        _dig({"bal": bal, "c": corr}, ("bal", "current1410"), ("c", "current1410"))
    )
    payables = _to_rub(
        _dig({"bal": bal, "c": corr}, ("bal", "current1520"), ("c", "current1520"))
    )

    return YearFinance(
        period=period,
        revenue=revenue,
        borrowed_short=borrowed_short,
        borrowed_long=borrowed_long,
        payables=payables,
    )


def _parse_response(r) -> Any:
    code = getattr(r, "status_code", 200)
    if code >= 400:
        raise RuntimeError(f"http_{code}")
    ctype = ""
    try:
        ctype = (r.headers.get("content-type") or "").lower()
    except Exception:
        pass
    text = r.text if hasattr(r, "text") else ""
    if "json" not in ctype and text.lstrip()[:1] not in ("{", "["):
        raise RuntimeError(f"non_json:{ctype}:{text[:80]!r}")
    return r.json()


def _try_json(session, url: str, params: dict | None = None) -> Any:
    """
    Запрос JSON. Редирект bo.nalog.ru → bo.nalog.gov.ru:
    если Location без path — сохраняем исходный API-путь на gov.ru.
    """
    r = http_get(session, url, params=params, allow_redirects=False)
    code = getattr(r, "status_code", 200)

    if code in (301, 302, 303, 307, 308):
        loc = ""
        try:
            loc = r.headers.get("location") or ""
        except Exception:
            loc = ""
        orig = urlparse(url)
        if not loc.startswith("http"):
            loc = f"{orig.scheme}://{orig.netloc}{loc}"

        loc_p = urlparse(loc)
        # 302 на корень gov.ru — переносим path+query API
        if "bo.nalog.gov.ru" in loc_p.netloc and (not loc_p.path or loc_p.path == "/"):
            q = orig.query
            if params:
                from urllib.parse import urlencode

                q = urlencode(params)
            loc = f"https://bo.nalog.gov.ru{orig.path}"
            if q:
                loc = f"{loc}?{q}"
            params = None  # уже в URL

        r = http_get(session, loc, params=params, allow_redirects=True)
        return _parse_response(r)

    return _parse_response(r)


def fetch_buh(inn: str, *, pause: float = 0.8) -> BuhReport:
    inn = (inn or "").strip()
    if not inn.isdigit() or len(inn) not in (10, 12):
        return BuhReport(inn=inn, error="bad_inn")

    bases = _bases()
    last_err = ""

    for base in bases:
        session = make_session(
            {
                "Referer": f"{base}/",
                "Origin": base,
            }
        )
        try:
            search = _try_json(
                session,
                f"{base}/advanced-search/organizations/search",
                {"query": inn, "page": "0"},
            )
            time.sleep(pause)
            content = search.get("content") if isinstance(search, dict) else None
            if not content:
                search = _try_json(
                    session,
                    f"{base}/nbo/organizations/search",
                    {"query": inn, "page": "0"},
                )
                time.sleep(pause)
                content = search.get("content") if isinstance(search, dict) else None

            if not content:
                last_err = "not_found"
                continue

            org = content[0]
            org_id = str(org.get("id") or "").replace("\xa0", "").replace(" ", "")
            name = (
                org.get("shortName") or org.get("fullName") or org.get("name") or ""
            ).strip()
            if not org_id:
                last_err = "no_org_id"
                continue

            try:
                bfo = _try_json(session, f"{base}/nbo/organizations/{org_id}/bfo")
            except Exception:
                bfo = _try_json(session, f"{base}/nbo/organizations/{org_id}/bfo/")
            time.sleep(pause)

            if isinstance(bfo, dict):
                bfo = bfo.get("content") or bfo.get("bfo") or bfo.get("data") or []
            if not isinstance(bfo, list):
                last_err = "bad_bfo_shape"
                continue

            years = [_parse_year_block(x) for x in bfo if isinstance(x, dict)]
            years.sort(key=lambda y: y.period or "", reverse=True)

            return BuhReport(
                inn=inn,
                org_id=org_id,
                name=name,
                years=years,
                source=base,
            )
        except Exception as e:  # noqa: BLE001
            last_err = str(e)
            continue

    return BuhReport(inn=inn, error=last_err or "unreachable")


def checklist_from_buh(report: BuhReport) -> dict[str, Any]:
    if report.error:
        return {"error": report.error}

    revenues: dict[str, int] = {}
    for y in report.years:
        if y.period and y.revenue is not None:
            revenues[y.period] = y.revenue

    recent = sorted(revenues.items(), key=lambda x: x[0], reverse=True)[:3]
    max_rev = max((v for _, v in recent), default=None)

    if max_rev is None and not report.years:
        r_flag = "НЕТ"
        u_flag = "НЕТ"
    elif max_rev is None:
        r_flag = ""
        u_flag = "ДА"
    else:
        r_flag = "ЕСТЬ" if max_rev > 500_000 else "НЕТ"
        u_flag = "ДА"

    k_parts: list[str] = []
    for y in report.years[:3]:
        bits = []
        if y.borrowed_long:
            bits.append(f"долгоср.займы={y.borrowed_long:,}".replace(",", " "))
        if y.borrowed_short:
            bits.append(f"кратк.займы={y.borrowed_short:,}".replace(",", " "))
        if y.payables:
            bits.append(f"кредиторка={y.payables:,}".replace(",", " "))
        if bits:
            k_parts.append(f"{y.period}: " + ", ".join(bits))
            break
    if not k_parts and report.years:
        k_parts.append(f"{report.years[0].period}: займы/кредиторка не указаны / 0")

    rev_text = ", ".join(
        f"{y}={v:,}".replace(",", " ") for y, v in recent if v is not None
    )

    return {
        "K_loans_payables": "; ".join(k_parts),
        "R_turnover": r_flag,
        "U_reports_filed": u_flag,
        "revenues": revenues,
        "revenue_recent_text": rev_text,
        "max_revenue_3y": max_rev,
        "periods": [y.period for y in report.years],
        "org_id": report.org_id,
        "name": report.name,
        "card_url": (
            f"https://bo.nalog.gov.ru/organizations-card/{report.org_id}"
            if report.org_id
            else ""
        ),
    }
