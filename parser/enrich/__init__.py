"""Обогащение лотов внешними источниками (ЕГРЮЛ, БФО и далее)."""

from .pipeline import enrich_db

__all__ = ["enrich_db"]
