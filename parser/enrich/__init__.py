"""Обогащение лотов внешними источниками (ЕГРЮЛ, БФО и далее)."""

from .pipeline import enrich_db, enrich_zsk_bot_db

__all__ = ["enrich_db", "enrich_zsk_bot_db"]
