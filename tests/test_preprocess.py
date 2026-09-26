"""Unit tests for game/team cleaning (no network)."""

import polars as pl

from nfl_data.preprocess import FALLBACK_ABBR_MAP, clean_games, clean_teams, empty_strings_to_null


def test_empty_strings_to_null() -> None:
    df = pl.DataFrame({"a": ["KC", "", "  "]})
    out = empty_strings_to_null(df)
    assert out["a"].to_list() == ["KC", None, None]


def test_clean_games_fixture_vs_final() -> None:
    schedules = pl.DataFrame(
        {
            "game_id": ["2025_01_KC_LAC", "2025_02_BUF_MIA", "2025_00_KC_GB"],
            "season": [2025, 2025, 2025],
            "week": [1, 2, 0],
            "game_type": ["REG", "REG", "PRE"],
            "gameday": ["2025-09-05", "2025-09-14", "2025-08-09"],
            "gametime": ["20:20", "13:00", "13:00"],
            "home_team": ["KC", "BUF", "KC"],
            "away_team": ["LAC", "MIA", "GB"],
            "home_score": [27, None, 10],
            "away_score": [20, None, 3],
            "overtime": [0, None, 0],
            "location": ["Home", "Home", "Home"],
            "stadium": ["Arrowhead", "Highmark", "Arrowhead"],
            "spread_line": [6.5, 3.0, 7.0],
            "total_line": [47.5, 48.0, 40.0],
            "espn": ["401671001", "401671002", "401671000"],
        }
    )
    games = clean_games(schedules, include_preseason=False, abbr_map=FALLBACK_ABBR_MAP)
    assert games.height == 2
    by_id = {row["game_id"]: row for row in games.to_dicts()}
    assert by_id["2025_01_KC_LAC"]["status"] == "final"
    assert by_id["2025_01_KC_LAC"]["home_score"] == 27
    assert by_id["2025_02_BUF_MIA"]["status"] == "scheduled"
    assert by_id["2025_02_BUF_MIA"]["home_score"] is None
    assert by_id["2025_01_KC_LAC"]["kickoff_at"] is not None
    assert by_id["2025_01_KC_LAC"]["espn_id"] == "401671001"
    assert by_id["2025_01_KC_LAC"]["overtime"] is False


def test_clean_games_normalizes_abbrs_and_dedupes() -> None:
    schedules = pl.DataFrame(
        {
            "game_id": ["2024_01_LV_LAC", "2024_01_LV_LAC"],
            "season": [2024, 2024],
            "week": [1, 1],
            "game_type": ["REG", "REG"],
            "gameday": ["2024-09-08", "2024-09-08"],
            "gametime": ["16:25", "16:25"],
            "home_team": ["OAK", "OAK"],
            "away_team": ["SD", "SD"],
            "home_score": [None, 22],
            "away_score": [None, 10],
            "overtime": [0, 0],
            "location": ["Home", "Home"],
            "stadium": ["Allegiant", "Allegiant"],
            "spread_line": [3.0, 3.0],
            "total_line": [44.0, 44.0],
            "espn": ["1", "1"],
        }
    )
    games = clean_games(schedules, abbr_map=FALLBACK_ABBR_MAP)
    assert games.height == 1
    row = games.row(0, named=True)
    assert row["home_team"] == "LV"
    assert row["away_team"] == "LAC"
    assert row["status"] == "final"


def test_clean_teams() -> None:
    teams = pl.DataFrame(
        {
            "team_abbr": ["KC", "OAK"],
            "team_name": ["Kansas City Chiefs", "Oakland Raiders"],
            "team_conf": ["AFC", "AFC"],
            "team_division": ["AFC West", "AFC West"],
        }
    )
    out = clean_teams(teams, abbr_map=FALLBACK_ABBR_MAP)
    abbrs = set(out["abbr"].to_list())
    assert abbrs == {"KC", "LV"}
    lv = out.filter(pl.col("abbr") == "LV").row(0, named=True)
    assert lv["conference"] == "AFC"


def test_ensure_teams_for_games_adds_stubs() -> None:
    from nfl_data.preprocess import ensure_teams_for_games

    teams = pl.DataFrame(
        {
            "abbr": ["KC", "LAR"],
            "full_name": ["Kansas City Chiefs", "Los Angeles Rams"],
            "conference": ["AFC", "NFC"],
            "division": ["AFC West", "NFC West"],
        }
    )
    games = pl.DataFrame({"home_team": ["KC"], "away_team": ["BUF"]})
    out = ensure_teams_for_games(teams, games)
    assert set(out["abbr"].to_list()) == {"KC", "BUF"}
    buf = out.filter(pl.col("abbr") == "BUF").row(0, named=True)
    assert buf["full_name"] is None
    # Historical extras not in games are dropped
    assert "LAR" not in out["abbr"].to_list()
