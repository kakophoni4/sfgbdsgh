"""
ЗСК через Telegram-бота @zskbenefitsarbot.

Шлём ИНН тем же Telethon-сеансом, что и scrape. Ответ вида:
  Текущий уровень риска ЗСК: 🟢 Низкий
"""
from __future__ import annotations

import asyncio
import re
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

from telethon import TelegramClient
from telethon.errors import FloodWaitError

BOT_USERNAME = "zskbenefitsarbot"

_RE_LEVEL = re.compile(
    r"уровень\s+риска\s+зск\s*:\s*(?:🟢|🟡|🔴|🟩|🟨|🟥)?\s*"
    r"(?P<label>низкий|средний|высоки[йя]|критическ\w*)",
    re.I,
)
_RE_EMOJI = re.compile(r"(🟢|🟡|🔴|🟩|🟨|🟥)")


@dataclass
class ZskBotReport:
    inn: str = ""
    level: str = ""  # green|yellow|red|unknown
    label: str = ""
    raw: str = ""
    error: str = ""
    source: str = BOT_USERNAME
    checked_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_zsk_reply(text: str) -> tuple[str, str]:
    """→ (level, label). level: green|yellow|red|unknown."""
    t = (text or "").strip()
    if not t:
        return "unknown", ""

    m = _RE_LEVEL.search(t)
    if m:
        label = m.group("label").strip()
        low = label.lower()
        if low.startswith("низк"):
            return "green", "Низкий"
        if low.startswith("средн"):
            return "yellow", "Средний"
        if low.startswith("высок") or low.startswith("крит"):
            return "red", "Высокий"
        return "unknown", label

    # fallback по emoji в сообщении про ЗСК
    if "зск" in t.lower() or "риск" in t.lower():
        em = _RE_EMOJI.search(t)
        if em:
            e = em.group(1)
            if e in {"🟢", "🟩"}:
                return "green", "Низкий"
            if e in {"🟡", "🟨"}:
                return "yellow", "Средний"
            if e in {"🔴", "🟥"}:
                return "red", "Высокий"
        low = t.lower()
        if "низк" in low:
            return "green", "Низкий"
        if "средн" in low:
            return "yellow", "Средний"
        if "высок" in low or "крит" in low:
            return "red", "Высокий"

    return "unknown", ""


def needs_zsk_bot(p: dict[str, Any]) -> bool:
    inn = (p.get("inn") or "").strip()
    if not (inn.isdigit() and len(inn) == 10):
        e_inn = str(((p.get("enrich") or {}).get("egrul") or {}).get("inn") or "").strip()
        if e_inn.isdigit() and len(e_inn) == 10:
            inn = e_inn
        else:
            return False
    block = ((p.get("enrich") or {}).get("zsk_bot") or {})
    level = str(block.get("level") or p.get("zsk_verified") or "")
    err = str(block.get("error") or "").split(":", 1)[0].strip().lower()
    if level in {"green", "yellow", "red"} and not block.get("error"):
        return False
    if err in {"no_reply", "parse_fail", "bad_inn", "bot_blocked", "not_authorized"}:
        return False
    return True


def _inn_of(p: dict[str, Any]) -> str:
    inn = (p.get("inn") or "").strip()
    if inn.isdigit() and len(inn) == 10:
        return inn
    e_inn = str(((p.get("enrich") or {}).get("egrul") or {}).get("inn") or "").strip()
    return e_inn if e_inn.isdigit() and len(e_inn) == 10 else ""


async def _fetch_one(
    client: TelegramClient,
    entity: Any,
    inn: str,
    *,
    timeout: float = 35.0,
) -> ZskBotReport:
    report = ZskBotReport(inn=inn, checked_at=_now())
    last_id = 0
    try:
        async for msg in client.iter_messages(entity, limit=1):
            last_id = int(msg.id or 0)
            break
    except Exception as e:  # noqa: BLE001
        report.error = f"history:{e}"
        return report

    try:
        await client.send_message(entity, inn)
    except FloodWaitError as e:
        report.error = f"flood:{e.seconds}"
        return report
    except Exception as e:  # noqa: BLE001
        err = str(e).lower()
        if "blocked" in err or "deactivated" in err:
            report.error = "bot_blocked"
        else:
            report.error = f"send:{e}"
        return report

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        await asyncio.sleep(1.2)
        try:
            async for msg in client.iter_messages(entity, limit=8):
                if msg.out:
                    continue
                if int(msg.id or 0) <= last_id:
                    break
                text = (msg.message or "").strip()
                if not text:
                    continue
                # ответ бота по нашему ИНН или общий шаблон ЗСК
                if inn not in text and "зск" not in text.lower() and "риск" not in text.lower():
                    continue
                level, label = parse_zsk_reply(text)
                report.raw = text[:800]
                report.level = level
                report.label = label
                if level in {"green", "yellow", "red"}:
                    return report
                report.error = "parse_fail"
                return report
        except FloodWaitError as e:
            report.error = f"flood:{e.seconds}"
            return report
        except Exception as e:  # noqa: BLE001
            report.error = f"read:{e}"
            return report

    report.error = "no_reply"
    return report


async def enrich_zsk_bot_async(
    payloads: list[dict[str, Any]],
    client: TelegramClient,
    *,
    pause: float = 3.0,
    timeout: float = 35.0,
    on_progress: Any = None,
) -> list[tuple[dict[str, Any], ZskBotReport]]:
    """Один connect снаружи. Возвращает (payload, report) по каждому кандидату."""
    try:
        entity = await client.get_entity(BOT_USERNAME)
    except Exception as e:  # noqa: BLE001
        err = ZskBotReport(error=f"entity:{e}", checked_at=_now())
        return [(p, err) for p in payloads]

    out: list[tuple[dict[str, Any], ZskBotReport]] = []
    n = len(payloads)
    for i, p in enumerate(payloads, 1):
        inn = _inn_of(p)
        if not inn:
            out.append((p, ZskBotReport(error="bad_inn", checked_at=_now())))
            continue
        if on_progress:
            on_progress(i, n, inn)
        report = await _fetch_one(client, entity, inn, timeout=timeout)
        out.append((p, report))
        if report.error.startswith("flood:"):
            try:
                wait_s = int(report.error.split(":", 1)[1])
            except ValueError:
                wait_s = 30
            await asyncio.sleep(min(max(wait_s, 5), 120))
        else:
            await asyncio.sleep(max(1.0, pause))
    return out


def apply_zsk_report(payload: dict[str, Any], report: ZskBotReport) -> dict[str, Any]:
    from parser.score import score_payload

    p = dict(payload)
    inn = _inn_of(p)
    if inn and not (p.get("inn") or "").strip():
        p["inn"] = inn
    block = report.to_dict()
    enrich = dict(p.get("enrich") or {})
    enrich["zsk_bot"] = block
    enrich["checked_at"] = _now()
    p["enrich"] = enrich
    if report.level in {"green", "yellow", "red"} and not report.error:
        p["zsk_verified"] = report.level
    p["scoring"] = score_payload(p)
    return p
