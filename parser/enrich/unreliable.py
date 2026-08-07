"""
Недостоверные сведения ЕГРЮЛ → колонка I.

I = ДА (достоверно / признаков нет), НЕТ (есть недостоверка), ПРОВЕРИТЬ.
Полная PDF-выписка часто требует сессии/капчи — сначала эвристики по карточке поиска.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any

UNRELIABLE_MARKERS = (
    "недостоверн",
    "сведения недостоверны",
    "признаны недостоверными",
    "недостоверные сведения",
)


@dataclass
class UnreliableReport:
    inn: str = ""
    unreliable: bool | None = None
    evidence: str = ""
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _scan_text(*parts: str) -> str | None:
    blob = " | ".join(p for p in parts if p)
    low = blob.lower()
    for m in UNRELIABLE_MARKERS:
        if m in low:
            # вырезать короткий контекст
            idx = low.find(m)
            snippet = blob[max(0, idx - 40) : idx + 80]
            return re.sub(r"\s+", " ", snippet).strip()
    return None


def check_unreliable_from_egrul(egrul: dict[str, Any] | None) -> UnreliableReport:
    egrul = egrul or {}
    inn = str(egrul.get("inn") or "")
    if egrul.get("error") and not inn:
        return UnreliableReport(error=str(egrul.get("error")))

    raw = egrul.get("raw") if isinstance(egrul.get("raw"), dict) else {}
    raw_blob = " ".join(str(v) for v in raw.values()) if raw else ""

    hit = _scan_text(
        str(egrul.get("address") or ""),
        str(egrul.get("status") or ""),
        str(egrul.get("name") or ""),
        str(egrul.get("director") or ""),
        raw_blob,
    )
    if hit:
        return UnreliableReport(inn=inn, unreliable=True, evidence=hit)

    # если карточка ЕГРЮЛ есть и маркеров нет — считаем ОК пока нет выписки
    if inn and not egrul.get("error"):
        return UnreliableReport(
            inn=inn,
            unreliable=False,
            evidence="маркеров недостоверности в карточке поиска нет (выписка не разбиралась)",
        )

    return UnreliableReport(inn=inn, unreliable=None, error="no_egrul")


def checklist_from_unreliable(report: UnreliableReport) -> dict[str, Any]:
    if report.unreliable is True:
        return {
            "I_reliable": "НЕТ",
            "I_note": f"недостоверка: {report.evidence}",
        }
    if report.unreliable is False:
        return {
            "I_reliable": "ДА",
            "I_note": report.evidence or "признаков недостоверности не видно",
        }
    return {
        "I_reliable": "ПРОВЕРИТЬ",
        "I_note": report.error or report.evidence or "нет данных ЕГРЮЛ",
    }
