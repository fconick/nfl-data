# NFL data pipeline

Python pipeline that downloads the last 3 NFL seasons with [nflreadpy](https://nflreadpy.nflverse.com/), cleans fixtures and final scores, then stores:

| Store | What | Consumers |
| --- | --- | --- |
| **S3** | Raw + cleaned parquet (schedules, PBP, player/team stats, rosters, games) | Notebooks, DuckDB, models |
| **Supabase** | `teams` + `games` only | App: upcoming fixtures, final scores, week views |

Play-by-play stays in S3. It is too wide for Postgres.

```
nflverse (nflreadpy)
        │
        ▼
   preprocess
        │
        ├── S3   raw/season=YYYY/*.parquet
        │        cleaned/season=YYYY/games.parquet
        │        cleaned/season=YYYY/pbp.parquet
        │
        └── Supabase  public.games / public.teams
                      views: fixtures, results
```

## Setup

Python 3.11+. [uv](https://docs.astral.sh/uv/) is preferred; pip works too.

```bash
# uv
uv sync --extra dev

# or pip
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

Copy env and fill in credentials:

```bash
cp .env.example .env
```

| Variable | Required for | Notes |
| --- | --- | --- |
| `S3_BUCKET` | S3 writes | Prefix defaults to `nfl` |
| `AWS_REGION` | S3 | Default `us-east-1` |
| `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` | S3 | Optional if using instance/role creds |
| `AWS_ENDPOINT_URL` | S3 | Optional MinIO/LocalStack |
| `SUPABASE_URL` | upserts | Project URL |
| `SUPABASE_SERVICE_ROLE_KEY` | upserts | ETL only; never ship this to a browser |

Apply [sql/001_schema.sql](sql/001_schema.sql) in the Supabase SQL editor (tables, indexes, `fixtures`/`results` views, public read RLS).

## Commands

Default seasons are current, current-1, and current-2 (`nflreadpy.get_current_season()`).

```bash
# Full lake + games upsert
uv run python -m nfl_data ingest

# In-season: schedules only, overwrite scores as games finish
uv run python -m nfl_data refresh-games

# Explicit years / skip a store (local testing)
uv run python -m nfl_data ingest --seasons 2024 2025 2026 --skip-s3
uv run python -m nfl_data refresh-games --skip-supabase --include-preseason
```

Both commands are idempotent: S3 overwrites the season partition; Postgres upserts on `game_id`.

## GitHub Actions

[`.github/workflows/weekly-ingest.yml`](.github/workflows/weekly-ingest.yml) runs `python -m nfl_data ingest --seasons 2026` every **Tuesday at 23:00 UTC** (7:00 PM Eastern in daylight time). Change `2026` to `2027` when that season starts. You can also run it from the Actions tab (**Run workflow**).

The repo must be on GitHub. Add these **Actions secrets** (Settings → Secrets and variables → Actions). Do not commit `.env`.

| Secret | Example |
| --- | --- |
| `AWS_ACCESS_KEY_ID` | Backblaze key ID (write access) |
| `AWS_SECRET_ACCESS_KEY` | Backblaze application key |
| `AWS_REGION` | `us-east-005` |
| `AWS_ENDPOINT_URL` | `https://s3.us-east-005.backblazeb2.com` |
| `S3_BUCKET` | `nfl-bucket` |
| `S3_PREFIX` | `nfl` |
| `SUPABASE_URL` | `https://YOUR_PROJECT.supabase.co` |
| `SUPABASE_SERVICE_ROLE_KEY` | service role key |

GitHub pauses scheduled workflows if the repo is idle for 60 days.

## App queries

Unplayed games have null scores and `status = 'scheduled'`. Completed games have both scores and `status = 'final'`.

```sql
select * from fixtures where season = 2026 order by kickoff_at;
select * from results where season = 2025 and week = 1;
```

Use the anon key in the app. ETL uses the service role so it can write despite RLS.

## Tests

```bash
uv run pytest
```

## License note

Most nflverse files are CC-BY 4.0. Credit nflverse if you publish work from this data.
