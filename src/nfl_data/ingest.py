"""Download nflverse datasets via nflreadpy."""

from __future__ import annotations

import logging
from datetime import date

import polars as pl

logger = logging.getLogger(__name__)


def current_season() -> int:
    """NFL season year (e.g. 2026 for the 2026-27 season)."""
    try:
        import nflreadpy as nfl

        return int(nfl.get_current_season())
    except Exception:
        today = date.today()
        # Super Bowl is in February; treat March as the new season year.
        return today.year if today.month >= 3 else today.year - 1


def last_n_seasons(n: int = 3) -> list[int]:
    end = current_season()
    return list(range(end - n + 1, end + 1))


def load_schedules(seasons: list[int]) -> pl.DataFrame:
    import nflreadpy as nfl

    logger.info("Loading schedules for seasons %s", seasons)
    return nfl.load_schedules(seasons=seasons)


def load_teams() -> pl.DataFrame:
    import nflreadpy as nfl

    logger.info("Loading teams")
    return nfl.load_teams()


def load_pbp(seasons: list[int]) -> pl.DataFrame:
    import nflreadpy as nfl

    logger.info("Loading play-by-play for seasons %s", seasons)
    return nfl.load_pbp(seasons=seasons)


def load_player_stats(seasons: list[int]) -> pl.DataFrame:
    import nflreadpy as nfl

    logger.info("Loading player stats for seasons %s", seasons)
    return nfl.load_player_stats(seasons=seasons, summary_level="week")


def load_team_stats(seasons: list[int]) -> pl.DataFrame:
    import nflreadpy as nfl

    logger.info("Loading team stats for seasons %s", seasons)
    return nfl.load_team_stats(seasons=seasons, summary_level="week")


def load_rosters(seasons: list[int]) -> pl.DataFrame:
    import nflreadpy as nfl

    logger.info("Loading rosters for seasons %s", seasons)
    return nfl.load_rosters(seasons=seasons)


def try_load(name: str, loader) -> pl.DataFrame | None:
    try:
        return loader()
    except Exception:
        logger.warning("Failed to load %s; continuing", name, exc_info=True)
        return None
