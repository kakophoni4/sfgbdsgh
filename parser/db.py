from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from .extract import Listing


SCHEMA = """
CREATE TABLE IF NOT EXISTS listings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER NOT NULL,
    message_id INTEGER NOT NULL,
    block_index INTEGER NOT NULL,
    inn TEXT,
    name TEXT,
    link TEXT,
    msg_date TEXT,
    payload TEXT NOT NULL,
    score INTEGER,
    verdict TEXT,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(chat_id, message_id, block_index)
);
"""


class ListingDB:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)

    def upsert(self, listing: Listing, scored: dict[str, Any]) -> None:
        # сохраняем enrich если запись уже была
        existing = self.get_payload(
            listing.chat_id, listing.message_id, listing.block_index
        )
        payload = listing.to_dict()
        if existing and existing.get("enrich"):
            payload["enrich"] = existing["enrich"]
        payload["scoring"] = scored
        # если уже есть enrich — пересчитаем score с ним
        if payload.get("enrich"):
            from .score import score_payload

            payload["scoring"] = score_payload(payload)
            scored = payload["scoring"]

        self._write_row(payload, scored)

    def save_payload(self, payload: dict[str, Any]) -> None:
        scored = payload.get("scoring") or {}
        self._write_row(payload, scored)

    def _write_row(self, payload: dict[str, Any], scored: dict[str, Any]) -> None:
        self.conn.execute(
            """
            INSERT INTO listings (
                chat_id, message_id, block_index, inn, name, link, msg_date,
                payload, score, verdict
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(chat_id, message_id, block_index) DO UPDATE SET
                inn=excluded.inn,
                name=excluded.name,
                link=excluded.link,
                msg_date=excluded.msg_date,
                payload=excluded.payload,
                score=excluded.score,
                verdict=excluded.verdict,
                updated_at=CURRENT_TIMESTAMP
            """,
            (
                payload.get("chat_id"),
                payload.get("message_id"),
                payload.get("block_index"),
                payload.get("inn"),
                payload.get("name"),
                payload.get("link"),
                payload.get("msg_date"),
                json.dumps(payload, ensure_ascii=False),
                scored.get("score"),
                scored.get("verdict"),
            ),
        )
        self.conn.commit()

    def get_payload(
        self, chat_id: int, message_id: int, block_index: int
    ) -> dict[str, Any] | None:
        row = self.conn.execute(
            """
            SELECT payload FROM listings
            WHERE chat_id=? AND message_id=? AND block_index=?
            """,
            (chat_id, message_id, block_index),
        ).fetchone()
        return json.loads(row["payload"]) if row else None

    def all_payloads(self) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT payload FROM listings ORDER BY score DESC, message_id DESC"
        ).fetchall()
        return [json.loads(r["payload"]) for r in rows]

    def stats(self) -> dict[str, int]:
        total = self.conn.execute("SELECT COUNT(*) c FROM listings").fetchone()["c"]
        with_inn = self.conn.execute(
            "SELECT COUNT(*) c FROM listings WHERE inn IS NOT NULL AND inn != ''"
        ).fetchone()["c"]
        yes = self.conn.execute(
            "SELECT COUNT(*) c FROM listings WHERE verdict='ДА'"
        ).fetchone()["c"]
        enriched = 0
        for row in self.conn.execute("SELECT payload FROM listings"):
            p = json.loads(row["payload"])
            e = (p.get("enrich") or {}).get("egrul") or {}
            if e.get("inn") and not e.get("error"):
                enriched += 1
        return {
            "total": total,
            "with_inn": with_inn,
            "verdict_yes": yes,
            "egrul_ok": enriched,
        }

    def close(self) -> None:
        self.conn.close()
