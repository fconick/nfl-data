"""NFL data ingest, preprocess, and hybrid store (S3 + Supabase)."""

from nfl_data.ingest import last_n_seasons

__all__ = ["last_n_seasons"]
