"""Clean nflverse frames into lake + app contracts."""

from __future__ import annotations

import logging

import polars as pl

logger = logging.getLogger(__name__)

# Relocations and common aliases. nflverse mapping is preferred when available.
FALLBACK_ABBR_MAP = {
    "OAK": "LV",
    "SD": "LAC",
    "STL": "LAR",
    "GNB": "GB",
    "KAN": "KC",
    "NWE": "NE",
    "NOR": "NO",
    "SFO": "SF",
    "TAM": "TB",
    "WSH": "WAS",
    "WFT": "WAS",
}

GAMES_COLUMNS = [
    "game_id",
    "season",
    "week",
    "game_type",
    "kickoff_at",
    "home_team",
    "away_team",
    "home_score",
    "away_score",
    "status",
    "overtime",
    "location",
    "stadium",
    "spread_line",
    "total_line",
    "espn_id",
]

TEAMS_COLUMNS = ["abbr", "full_name", "conference", "division"]

EMPTY_GAMES_SCHEMA = {
    "game_id": pl.String,
    "season": pl.Int64,
    "week": pl.Int64,
    "game_type": pl.String,
    "kickoff_at": pl.Datetime(time_zone="UTC"),
    "home_team": pl.String,
    "away_team": pl.String,
    "home_score": pl.Int64,
    "away_score": pl.Int64,
    "status": pl.String,
    "overtime": pl.Boolean,
    "location": pl.String,
    "stadium": pl.String,
    "spread_line": pl.Float64,
    "total_line": pl.Float64,
    "espn_id": pl.String,
}

EMPTY_TEAMS_SCHEMA = {col: pl.String for col in TEAMS_COLUMNS}


def team_abbr_map() -> dict[str, str]:
    try:
        import nflreadpy as nfl

        mapping = nfl.team_abbr_mapping()
        names = mapping["name"].to_list()
        values = mapping["value"].to_list()
        return {str(k): str(v) for k, v in zip(names, values) if k and v}
    except Exception:
        logger.info("Using fallback team abbreviation map")
        return dict(FALLBACK_ABBR_MAP)


def empty_strings_to_null(df: pl.DataFrame) -> pl.DataFrame:
    str_cols = [name for name, dtype in df.schema.items() if dtype == pl.String]
    if not str_cols:
        return df
    return df.with_columns(
        [
            pl.when(pl.col(col).str.strip_chars() == "")
            .then(pl.lit(None, dtype=pl.String))
            .otherwise(pl.col(col))
            .alias(col)
            for col in str_cols
        ]
    )


def _gameday_str() -> pl.Expr:
    return pl.col("gameday").cast(pl.Utf8).str.slice(0, 10)


def _gametime_hhmm() -> pl.Expr:
    raw = (
        pl.col("gametime")
        .cast(pl.Utf8)
        .str.strip_chars()
        .str.extract(r"(\d{1,2}:\d{2})", 1)
    )
    padded = (
        pl.when(raw.str.len_chars() == 4)
        .then(pl.concat_str([pl.lit("0"), raw]))
        .otherwise(raw.str.slice(0, 5))
    )
    return padded


def _kickoff_at(df: pl.DataFrame) -> pl.Expr:
    date_only = _gameday_str().str.to_datetime(
        "%Y-%m-%d",
        time_zone="America/New_York",
        strict=False,
    )
    if "gametime" not in df.columns:
        return date_only.dt.convert_time_zone("UTC").alias("kickoff_at")

    combined = pl.concat_str([_gameday_str(), pl.lit(" "), _gametime_hhmm()])
    parsed = combined.str.to_datetime(
        "%Y-%m-%d %H:%M",
        time_zone="America/New_York",
        strict=False,
    )
    return (
        pl.when(parsed.is_not_null())
        .then(parsed)
        .otherwise(date_only)
        .dt.convert_time_zone("UTC")
        .alias("kickoff_at")
    )


def _normalize_abbr(col: str, mapping: dict[str, str]) -> pl.Expr:
    expr = pl.col(col).cast(pl.Utf8).str.strip_chars().str.to_uppercase()
    if mapping:
        expr = expr.replace(mapping)
    return expr.alias(col)


def _col(df: pl.DataFrame, name: str, *aliases: str) -> pl.Expr:
    for candidate in (name, *aliases):
        if candidate in df.columns:
            return pl.col(candidate)
    return pl.lit(None)


def clean_games(
    schedules: pl.DataFrame,
    *,
    include_preseason: bool = False,
    abbr_map: dict[str, str] | None = None,
) -> pl.DataFrame:
    """Turn raw schedules into one row per game (fixture or final)."""
    if schedules.is_empty():
        return pl.DataFrame(schema=EMPTY_GAMES_SCHEMA)

    mapping = abbr_map if abbr_map is not None else team_abbr_map()
    df = empty_strings_to_null(schedules)

    if not include_preseason and "game_type" in df.columns:
        df = df.filter(pl.col("game_type") != "PRE")

    if "game_id" in df.columns:
        if "home_score" in df.columns:
            df = df.with_columns(pl.col("home_score").is_not_null().alias("_has_score"))
            df = df.sort("_has_score").unique(subset=["game_id"], keep="last").drop("_has_score")
        else:
            df = df.unique(subset=["game_id"], keep="last", maintain_order=True)

    df = df.with_columns(
        [
            _normalize_abbr("home_team", mapping) if "home_team" in df.columns else pl.lit(None).alias("home_team"),
            _normalize_abbr("away_team", mapping) if "away_team" in df.columns else pl.lit(None).alias("away_team"),
        ]
    )

    home_score = _col(df, "home_score").cast(pl.Int64)
    away_score = _col(df, "away_score").cast(pl.Int64)
    status = (
        pl.when(home_score.is_not_null() & away_score.is_not_null())
        .then(pl.lit("final"))
        .otherwise(pl.lit("scheduled"))
        .alias("status")
    )

    overtime = _col(df, "overtime").cast(pl.Int64, strict=False).fill_null(0) > 0

    out = df.select(
        [
            _col(df, "game_id").cast(pl.Utf8).alias("game_id"),
            _col(df, "season").cast(pl.Int64).alias("season"),
            _col(df, "week").cast(pl.Int64).alias("week"),
            _col(df, "game_type").cast(pl.Utf8).alias("game_type"),
            _kickoff_at(df) if "gameday" in df.columns else pl.lit(None).alias("kickoff_at"),
            pl.col("home_team"),
            pl.col("away_team"),
            home_score.alias("home_score"),
            away_score.alias("away_score"),
            status,
            overtime.alias("overtime"),
            _col(df, "location").cast(pl.Utf8).alias("location"),
            _col(df, "stadium").cast(pl.Utf8).alias("stadium"),
            _col(df, "spread_line").cast(pl.Float64).alias("spread_line"),
            _col(df, "total_line").cast(pl.Float64).alias("total_line"),
            _col(df, "espn_id", "espn").cast(pl.Utf8).alias("espn_id"),
        ]
    ).filter(pl.col("game_id").is_not_null())

    return out.sort(["season", "week", "kickoff_at", "game_id"])


def clean_teams(teams: pl.DataFrame, *, abbr_map: dict[str, str] | None = None) -> pl.DataFrame:
    if teams.is_empty():
        return pl.DataFrame(schema=EMPTY_TEAMS_SCHEMA)

    mapping = abbr_map if abbr_map is not None else team_abbr_map()
    df = empty_strings_to_null(teams)
    abbr_src = "team_abbr" if "team_abbr" in df.columns else "abbr"
    name_src = "team_name" if "team_name" in df.columns else "full_name"
    conf_src = "team_conf" if "team_conf" in df.columns else (
        "team_conference" if "team_conference" in df.columns else None
    )
    div_src = "team_division" if "team_division" in df.columns else "division"

    df = df.with_columns(_normalize_abbr(abbr_src, mapping))
    out = df.select(
        [
            pl.col(abbr_src).alias("abbr"),
            pl.col(name_src).cast(pl.Utf8).alias("full_name") if name_src in df.columns else pl.lit(None).alias("full_name"),
            pl.col(conf_src).cast(pl.Utf8).alias("conference") if conf_src else pl.lit(None).alias("conference"),
            pl.col(div_src).cast(pl.Utf8).alias("division") if div_src in df.columns else pl.lit(None).alias("division"),
        ]
    ).unique(subset=["abbr"], keep="last")
    return out.filter(pl.col("abbr").is_not_null()).sort("abbr")


def ensure_teams_for_games(
    teams: pl.DataFrame,
    games: pl.DataFrame,
    *,
    drop_unused: bool = True,
) -> pl.DataFrame:
    """Ensure every game abbr exists in teams; drop historical extras by default."""
    if games.is_empty():
        return teams
    used = pl.concat(
        [
            games.select(pl.col("home_team").alias("abbr")),
            games.select(pl.col("away_team").alias("abbr")),
        ]
    ).unique()
    missing = used.join(teams, on="abbr", how="anti").filter(pl.col("abbr").is_not_null())
    if not missing.is_empty():
        stubs = missing.with_columns(
            [
                pl.lit(None, dtype=pl.String).alias("full_name"),
                pl.lit(None, dtype=pl.String).alias("conference"),
                pl.lit(None, dtype=pl.String).alias("division"),
            ]
        )
        teams = pl.concat([teams, stubs], how="diagonal_relaxed").unique(
            subset=["abbr"], keep="first"
        )
    if drop_unused:
        teams = teams.join(used, on="abbr", how="semi")
    return teams.sort("abbr") if "abbr" in teams.columns else teams


def clean_wide(df: pl.DataFrame) -> pl.DataFrame:
    """Light cleanup for PBP / stats / rosters parquet."""
    if df.is_empty():
        return df
    return empty_strings_to_null(df)
