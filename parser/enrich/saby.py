"""
Saby (СБИС) profile — запасной источник для I (недостоверки).

https://saby.ru/profile/{inn}
В HTML часто лежит JSON с ключами НедостоверностьАдреса / Управляющего / Учредителя.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any

from .http_util import http_get, make_session

BASE = "https://saby.ru"


@dataclass
class SabyReport:
    inn: str = ""
    url: str = ""
    unreliable: bool | None = None
    evidence: str = ""
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def fetch_saby(inn: str) -> SabyReport:
    inn = (inn or "").strip()
    if not inn.isdigit() or len(inn) not in (10, 12):
        return SabyReport(inn=inn, error="bad_inn")

    url = f"{BASE}/profile/{inn}"
    session = make_session({"Accept": "text/html", "Referer": f"{BASE}/"})
    try:
        r = http_get(session, url, timeout=35, allow_redirects=True)
        code = getattr(r, "status_code", 0)
        html = r.text if hasattr(r, "text") else ""
        if code >= 400:
            return SabyReport(inn=inn, url=url, error=f"http_{code}")
        if "captcha" in (html or "").lower() and len(html) < 5000:
            return SabyReport(inn=inn, url=url, error="captcha")

        # {"НедостоверностьАдреса":null,...}
        m = re.search(
            r'"НедостоверностьАдреса"\s*:\s*(null|true|false|"[^"]*")\s*,\s*'
            r'"НедостоверностьУправляющего"\s*:\s*(null|true|false|"[^"]*")\s*,\s*'
            r'"НедостоверностьУчредителя"\s*:\s*(null|true|false|"[^"]*")',
            html or "",
        )
        if not m:
            # softer search
            if "НедостоверностьАдреса" not in (html or ""):
                return SabyReport(inn=inn, url=url, error="no_unreliable_block")
            vals = re.findall(
                r'"Недостоверность(?:Адреса|Управляющего|Учредителя)"\s*:\s*(null|true|false)',
                html or "",
            )
            if not vals:
                return SabyReport(inn=inn, url=url, error="parse_empty")
            bad = any(v == "true" for v in vals)
            return SabyReport(
                inn=inn,
                url=url,
                unreliable=bad,
                evidence="saby flags=" + ",".join(vals),
            )

        flags = [m.group(1), m.group(2), m.group(3)]
        bad = any(f == "true" for f in flags)
        # null/false = ok
        return SabyReport(
            inn=inn,
            url=str(getattr(r, "url", url)),
            unreliable=bad,
            evidence="addr=%s director=%s founder=%s" % tuple(flags),
        )
    except Exception as e:  # noqa: BLE001
        return SabyReport(inn=inn, url=url, error=str(e))


def checklist_from_saby(report: SabyReport) -> dict[str, Any]:
    out: dict[str, Any] = {"saby_url": report.url}
    if report.error and report.unreliable is None:
        out["saby_error"] = report.error
        return out
    if report.unreliable is True:
        out["I_reliable"] = "НЕТ"
        out["I_note"] = f"Saby: недостоверность ({report.evidence})"
    elif report.unreliable is False:
        out["I_reliable"] = "ДА"
        out["I_note"] = f"Saby: недостоверности нет ({report.evidence})"
    return out
