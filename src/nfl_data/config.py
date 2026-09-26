"""Environment-driven settings for S3 and Supabase."""

from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import urlparse

from dotenv import load_dotenv

load_dotenv()


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip()
    return text or None


def infer_region(region: str, endpoint_url: str | None) -> str:
    """Prefer the region embedded in a Backblaze endpoint over a stale AWS default."""
    if not endpoint_url:
        return region
    host = urlparse(endpoint_url).hostname or ""
    # s3.us-east-005.backblazeb2.com
    if host.startswith("s3.") and host.endswith(".backblazeb2.com"):
        return host.split(".")[1]
    return region


def addressing_style_for(endpoint_url: str | None, override: str = "auto") -> str:
    """Backblaze/R2 need virtual-hosted URLs; local MinIO needs path-style."""
    if override in {"path", "virtual"}:
        return override
    if not endpoint_url:
        return "auto"
    host = (urlparse(endpoint_url).hostname or "").lower()
    if host in {"localhost", "127.0.0.1"} or host.endswith(".local"):
        return "path"
    if "backblazeb2.com" in host or "r2.cloudflarestorage.com" in host:
        return "virtual"
    return "virtual"


@dataclass(frozen=True)
class Settings:
    aws_access_key_id: str | None
    aws_secret_access_key: str | None
    aws_region: str
    aws_endpoint_url: str | None
    s3_bucket: str
    s3_prefix: str
    s3_addressing_style: str
    supabase_url: str
    supabase_service_role_key: str

    def require_s3(self) -> None:
        if not self.s3_bucket:
            raise RuntimeError("S3_BUCKET is not set")

    def require_supabase(self) -> None:
        if not self.supabase_url or not self.supabase_service_role_key:
            raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set")


def load_settings() -> Settings:
    endpoint = _clean(os.getenv("AWS_ENDPOINT_URL"))
    if endpoint:
        endpoint = endpoint.rstrip("/")
    region = infer_region(os.getenv("AWS_REGION", "us-east-1").strip() or "us-east-1", endpoint)
    override = (os.getenv("S3_ADDRESSING_STYLE") or "auto").strip().lower()
    return Settings(
        aws_access_key_id=_clean(os.getenv("AWS_ACCESS_KEY_ID")),
        aws_secret_access_key=_clean(os.getenv("AWS_SECRET_ACCESS_KEY")),
        aws_region=region,
        aws_endpoint_url=endpoint,
        s3_bucket=(os.getenv("S3_BUCKET") or "").strip(),
        s3_prefix=(os.getenv("S3_PREFIX") or "nfl").strip().strip("/"),
        s3_addressing_style=addressing_style_for(endpoint, override),
        supabase_url=_clean(os.getenv("SUPABASE_URL")) or "",
        supabase_service_role_key=_clean(os.getenv("SUPABASE_SERVICE_ROLE_KEY")) or "",
    )
