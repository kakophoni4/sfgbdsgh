from __future__ import annotations

import socket
import time
from dataclasses import asdict, dataclass, field
from typing import Any

from .http_util import http_get, make_session

BASE = "https://bo.nalog.gov.ru"


def _host_ok(host: str) -> bool:
    try:
        socket.gethostbyname(host)
        return True
    except Exception:
        return False


@dataclass
class YearFinance:
    period: str = ""
    revenue: int | None = None  # руб, строка 2110 / gainSum
    borrowed_short: int | None = None  # 1510
    borrowed_long: int | None = None  # 1410
    payables: int | None = None  # 1520


@dataclass
class BuhReport:
    inn: str = ""
    org_id: str = ""
    name: str = ""
    years: list[YearFinance] = field(default_factory=list)
    error: str = ""
    source: str = BASE

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

    revenue = None
    if isinstance(fr, dict):
        revenue = _to_rub(fr.get("current2110"))
    if revenue is None and block.get("gainSum") is not None:
        revenue = _to_rub(block.get("gainSum"))

    borrowed_short = _to_rub(bal.get("current1510")) if bal else None
    borrowed_long = _to_rub(bal.get("current1410")) if bal else None
    payables = _to_rub(bal.get("current1520")) if bal else None

    return YearFinance(
        period=period,
        revenue=revenue,
        borrowed_short=borrowed_short,
        borrowed_long=borrowed_long,
        payables=payables,
    )


def _json(session, url: str, params: dict | None = None) -> Any:
    r = http_get(session, url, params=params, allow_redirects=True, timeout=45)
    code = getattr(r, "status_code", 200)
    if code >= 400:
        raise RuntimeError(f"http_{code}")
    text = r.text if hasattr(r, "text") else ""
    ctype = ""
    try:
        ctype = (r.headers.get("content-type") or "").lower()
    except Exception:
        pass
    if "json" not in ctype and text.lstrip()[:1] not in ("{", "["):
        raise RuntimeError(f"non_json:{ctype}:{text[:80]!r}")
    return r.json()


def fetch_buh(inn: str, *, pause: float = 0.8) -> BuhReport:
    """
    Актуальный API (bo.nalog.gov.ru):
      GET /advanced-search/organizations?inn=&page=0&allFieldsMatch=false
      GET /nbo/organizations/{id}/bfo
    """
    inn = (inn or "").strip()
    if not inn.isdigit() or len(inn) not in (10, 12):
        return BuhReport(inn=inn, error="bad_inn")
    if not _host_ok("bo.nalog.gov.ru") and not _host_ok("bo.nalog.ru"):
        return BuhReport(inn=inn, error="dns_fail")

    base = BASE if _host_ok("bo.nalog.gov.ru") else "https://bo.nalog.ru"
    session = make_session(
        {
            "Referer": f"{base}/",
            "Origin": base,
            "Accept": "application/json, text/plain, */*",
        }
    )

    try:
        try:
            http_get(session, f"{base}/", allow_redirects=True, timeout=25)
        except Exception:
            pass
        time.sleep(min(pause, 1.0))

        # без period — надёжнее для молодых ООО; с period — fallback
        content = []
        last_err = "not_found"
        for params in (
            {"inn": inn, "page": 0, "allFieldsMatch": "false"},
            {"inn": inn, "page": 0, "allFieldsMatch": "false", "period": 2024},
            {"inn": inn, "page": 0, "allFieldsMatch": "false", "period": 2023},
            {"ogrn": inn, "page": 0, "allFieldsMatch": "false"}  # на случай если передали ОГРН
            if len(inn) == 13
            else None,
        ):
            if not params:
                continue
            try:
                data = _json(session, f"{base}/advanced-search/organizations", params)
            except Exception as e:  # noqa: BLE001
                last_err = str(e)
                continue
            content = data.get("content") or []
            if content:
                break
            last_err = "not_found"
            time.sleep(0.3)

        if not content:
            # банк / закрытая отчётность часто даёт пусто
            return BuhReport(inn=inn, error=last_err, source=base)

        org = content[0]
        org_id = str(org.get("id") or "").replace("\xa0", "").replace(" ", "")
        name = (
            org.get("shortName") or org.get("fullName") or org.get("name") or ""
        ).strip()
        # убрать html <strong> из подсветки
        name = name.replace("<strong>", "").replace("</strong>", "")
        if not org_id:
            return BuhReport(inn=inn, error="no_org_id", source=base)

        time.sleep(pause)
        bfo = _json(session, f"{base}/nbo/organizations/{org_id}/bfo")
        if isinstance(bfo, dict):
            bfo = bfo.get("content") or bfo.get("bfo") or bfo.get("data") or []
        if not isinstance(bfo, list):
            return BuhReport(inn=inn, org_id=org_id, name=name, error="bad_bfo_shape", source=base)

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
        return BuhReport(inn=inn, error=str(e), source=base)


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
            f"{BASE}/organizations-card/{report.org_id}" if report.org_id else ""
        ),
    }
