"""CLI: ingest last 3 seasons, or refresh fixtures/scores only."""

from __future__ import annotations

import argparse
import logging
import sys

import polars as pl

from nfl_data.config import load_settings
from nfl_data import ingest
from nfl_data.preprocess import clean_games, clean_teams, clean_wide, ensure_teams_for_games
from nfl_data.s3 import S3Lake
from nfl_data.supabase_store import SupabaseStore

logger = logging.getLogger(__name__)


def _add_common_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--seasons",
        nargs="+",
        type=int,
        help="Season years (default: last 3 including current)",
    )
    parser.add_argument(
        "--include-preseason",
        action="store_true",
        help="Keep PRE games (dropped by default)",
    )
    parser.add_argument("--skip-s3", action="store_true", help="Do not write parquet to S3")
    parser.add_argument(
        "--skip-supabase",
        action="store_true",
        help="Do not upsert teams/games into Supabase",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="nfl-data",
        description="Download nflverse data, clean fixtures/scores, store in S3 and Supabase.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    ingest_parser = sub.add_parser(
        "ingest",
        help="Download last 3 seasons (schedules, PBP, stats, rosters) and publish",
    )
    _add_common_flags(ingest_parser)

    refresh = sub.add_parser(
        "refresh-games",
        help="Reload schedules only and upsert fixtures/final scores",
    )
    _add_common_flags(refresh)
    return parser


def _seasons(args: argparse.Namespace) -> list[int]:
    return args.seasons or ingest.last_n_seasons(3)


def _write_s3(lake: S3Lake, stage: str, name: str, df: pl.DataFrame | None) -> None:
    if df is None:
        return
    lake.write_frame(df, stage, name)


def _publish(
    *,
    seasons: list[int],
    include_preseason: bool,
    skip_s3: bool,
    skip_supabase: bool,
    full: bool,
) -> None:
    settings = load_settings()
    schedules = ingest.load_schedules(seasons)
    teams_raw = ingest.try_load("teams", ingest.load_teams)

    cleaned_games = clean_games(schedules, include_preseason=include_preseason)
    if teams_raw is not None:
        cleaned_teams = clean_teams(teams_raw)
    else:
        cleaned_teams = pl.DataFrame(
            schema={
                "abbr": pl.String,
                "full_name": pl.String,
                "conference": pl.String,
                "division": pl.String,
            }
        )
    cleaned_teams = ensure_teams_for_games(cleaned_teams, cleaned_games)

    extras: dict[str, pl.DataFrame | None] = {}
    if full:
        extras = {
            "pbp": ingest.try_load("pbp", lambda: ingest.load_pbp(seasons)),
            "player_stats": ingest.try_load(
                "player_stats", lambda: ingest.load_player_stats(seasons)
            ),
            "team_stats": ingest.try_load(
                "team_stats", lambda: ingest.load_team_stats(seasons)
            ),
            "rosters": ingest.try_load("rosters", lambda: ingest.load_rosters(seasons)),
        }

    if not skip_s3:
        lake = S3Lake(settings)
        _write_s3(lake, "raw", "schedules", schedules)
        _write_s3(lake, "raw", "teams", teams_raw)
        _write_s3(lake, "cleaned", "games", cleaned_games)
        _write_s3(lake, "cleaned", "teams", cleaned_teams)
        for name, frame in extras.items():
            _write_s3(lake, "raw", name, frame)
            _write_s3(lake, "cleaned", name, clean_wide(frame) if frame is not None else None)

    if not skip_supabase:
        if cleaned_teams.is_empty():
            raise RuntimeError("Cannot upsert games without teams; load_teams failed")
        store = SupabaseStore(settings)
        store.upsert_teams(cleaned_teams)
        store.upsert_games(cleaned_games)

    logger.info(
        "Done. seasons=%s games=%s (%s final, %s scheduled)",
        seasons,
        cleaned_games.height,
        cleaned_games.filter(pl.col("status") == "final").height if cleaned_games.height else 0,
        cleaned_games.filter(pl.col("status") == "scheduled").height if cleaned_games.height else 0,
    )


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    args = build_parser().parse_args(argv)
    seasons = _seasons(args)
    logger.info("Using seasons %s", seasons)
    try:
        _publish(
            seasons=seasons,
            include_preseason=args.include_preseason,
            skip_s3=args.skip_s3,
            skip_supabase=args.skip_supabase,
            full=args.command == "ingest",
        )
    except Exception:
        logger.exception("Command failed")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
