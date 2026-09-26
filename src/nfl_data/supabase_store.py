"""Upsert teams and games into Supabase Postgres."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import polars as pl
from supabase import Client, create_client

from nfl_data.config import Settings
from nfl_data.preprocess import GAMES_COLUMNS, TEAMS_COLUMNS

logger = logging.getLogger(__name__)

BATCH_SIZE = 500


def _jsonable(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if hasattr(value, "isoformat"):
        text = value.isoformat()
        if getattr(value, "tzinfo", None) is not None and text.endswith("+00:00"):
            return text[:-6] + "Z"
        return text
    if isinstance(value, float) and value != value:  # NaN
        return None
    return value


def _records(df: pl.DataFrame, columns: list[str]) -> list[dict[str, Any]]:
    present = [c for c in columns if c in df.columns]
    rows: list[dict[str, Any]] = []
    for raw in df.select(present).to_dicts():
        rows.append({k: _jsonable(v) for k, v in raw.items()})
    return rows


class SupabaseStore:
    def __init__(self, settings: Settings, client: Client | None = None) -> None:
        settings.require_supabase()
        self._client = client or create_client(
            settings.supabase_url,
            settings.supabase_service_role_key,
        )

    def _upsert(self, table: str, rows: list[dict[str, Any]], on_conflict: str) -> None:
        if not rows:
            logger.info("No rows to upsert into %s", table)
            return
        for i in range(0, len(rows), BATCH_SIZE):
            batch = rows[i : i + BATCH_SIZE]
            self._client.table(table).upsert(batch, on_conflict=on_conflict).execute()
            logger.info("Upserted %s rows into %s (%s-%s)", len(batch), table, i + 1, i + len(batch))

    def upsert_teams(self, teams: pl.DataFrame) -> None:
        self._upsert("teams", _records(teams, TEAMS_COLUMNS), on_conflict="abbr")

    def upsert_games(self, games: pl.DataFrame) -> None:
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        rows = _records(games, GAMES_COLUMNS)
        for row in rows:
            row["updated_at"] = now
        self._upsert("games", rows, on_conflict="game_id")
