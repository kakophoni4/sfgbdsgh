"""Isolated, bounded source calls for file checks (no dependency on listing scoring)."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

SOURCES = (
    "egrul",
    "buh",
    "companium",
    "checko",
    "kad",
    "fssp",
    "fedresurs",
    "saby",
    "zsk_bot",
)
SOURCE_NAMES = {
    "egrul": "ЕГРЮЛ",
    "buh": "Бухгалтерская отчётность",
    "companium": "Companium",
    "checko": "Checko",
    "kad": "КАД",
    "fssp": "ФССП",
    "fedresurs": "Федресурс",
    "saby": "СБИС",
    "zsk_bot": "ЗСК",
}


async def _zsk(inn: str) -> dict:
    from tg_client import make_client
    from parser.enrich.zsk_bot import BOT_USERNAME, ZskBotReport, _fetch_one

    if len(inn) != 10:
        return ZskBotReport(inn=inn, error="unsupported_individual_inn").to_dict()
    client = make_client()
    await client.connect()
    try:
        if not await client.is_user_authorized():
            return ZskBotReport(inn=inn, error="not_authorized").to_dict()
        entity = await client.get_entity(BOT_USERNAME)
        report = await _fetch_one(client, entity, inn, require_correlation=True)
        return report.to_dict()
    finally:
        await client.disconnect()


def fetch_source(source: str, company: dict) -> dict:
    inn = company["inn"]
    ogrn = company.get("ogrn") or ""
    if source == "egrul":
        from parser.enrich.egrul import lookup_company

        return lookup_company(inn=inn).to_dict()
    if source == "buh":
        from parser.enrich.buh import fetch_buh

        return fetch_buh(inn).to_dict()
    if source in {"companium", "checko"}:
        if not ogrn:
            return {"error": "no_verified_ogrn", "inn": inn}
        if source == "companium":
            from parser.enrich.companium import fetch_companium

            return fetch_companium(ogrn=ogrn, inn=inn).to_dict()
        from parser.enrich.checko import fetch_checko

        return fetch_checko(ogrn=ogrn, inn=inn).to_dict()
    if source == "kad":
        from parser.enrich.kad import fetch_kad

        return fetch_kad(inn).to_dict()
    if source == "fssp":
        from parser.enrich.fssp import fetch_fssp

        return fetch_fssp(inn).to_dict()
    if source == "fedresurs":
        from parser.enrich.fedresurs import fetch_fedresurs, fetch_disqualified

        report = fetch_fedresurs(inn).to_dict()
        director = company.get("director") or ""
        if director:
            found, note = fetch_disqualified(director)
            report["disqualified"] = {"found": found, "note": note}
        return report
    if source == "saby":
        from parser.enrich.saby import fetch_saby

        report = fetch_saby(inn).to_dict()
        if report.get("unreliable") is False and "null" in str(
            report.get("evidence") or ""
        ):
            report["unreliable"] = None
            report["evidence"] += "; часть признаков не заполнена источником"
        return report
    if source == "zsk_bot":
        return asyncio.run(_zsk(inn))
    raise ValueError("Unknown source")


def main() -> None:
    source, input_path, output_path = sys.argv[1:]
    company = json.loads(Path(input_path).read_text(encoding="utf-8"))
    try:
        result = fetch_source(source, company)
        if (
            source == "egrul"
            and not result.get("error")
            and result.get("inn") != company["inn"]
        ):
            result = {"error": "inn_mismatch", "inn": company["inn"]}
    except Exception as exc:
        result = {"error": f"{type(exc).__name__}: {str(exc)[:300]}"}
    path = Path(output_path)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    temp.replace(path)


if __name__ == "__main__":
    main()
