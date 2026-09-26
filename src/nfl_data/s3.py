"""Write parquet to S3 with hive-style season partitions."""

from __future__ import annotations

import io
import logging

import boto3
import polars as pl
from botocore.config import Config

from nfl_data.config import Settings

logger = logging.getLogger(__name__)


def _drop_expect_header(request, **kwargs) -> None:
    request.headers.pop("Expect", None)
    request.headers.pop("expect", None)


class S3Lake:
    def __init__(self, settings: Settings) -> None:
        settings.require_s3()
        session_kwargs: dict = {"region_name": settings.aws_region}
        if settings.aws_access_key_id and settings.aws_secret_access_key:
            session_kwargs["aws_access_key_id"] = settings.aws_access_key_id
            session_kwargs["aws_secret_access_key"] = settings.aws_secret_access_key
        s3_cfg: dict = {}
        if settings.s3_addressing_style in {"path", "virtual"}:
            s3_cfg["addressing_style"] = settings.s3_addressing_style
        # boto3 1.36+ sends CRC checksums by default; B2 closes the connection.
        client_kwargs: dict = {
            "config": Config(
                signature_version="s3v4",
                request_checksum_calculation="when_required",
                response_checksum_validation="when_required",
                retries={"max_attempts": 4, "mode": "standard"},
                s3=s3_cfg,
            )
        }
        if settings.aws_endpoint_url:
            client_kwargs["endpoint_url"] = settings.aws_endpoint_url
        self._client = boto3.client("s3", **session_kwargs, **client_kwargs)
        # WSL1 + B2 drop the HTTP status line when boto3 sends Expect: 100-continue.
        self._client.meta.events.register("before-send.s3.*", _drop_expect_header)
        logger.info(
            "S3 client region=%s endpoint=%s addressing=%s bucket=%s",
            settings.aws_region,
            settings.aws_endpoint_url or "aws-default",
            settings.s3_addressing_style,
            settings.s3_bucket,
        )
        self.bucket = settings.s3_bucket
        self.prefix = settings.s3_prefix

    def key(self, stage: str, name: str, season: int | None = None) -> str:
        parts = [self.prefix, stage]
        if season is not None:
            parts.append(f"season={season}")
        parts.append(f"{name}.parquet")
        return "/".join(p.strip("/") for p in parts if p)

    def put_parquet(self, df: pl.DataFrame, key: str) -> str:
        buf = io.BytesIO()
        df.write_parquet(buf, compression="zstd")
        body = buf.getvalue()
        self._client.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=body,
            ContentLength=len(body),
            ContentType="application/vnd.apache.parquet",
        )
        uri = f"s3://{self.bucket}/{key}"
        logger.info("Wrote %s (%s rows, %s bytes)", uri, df.height, len(body))
        return uri

    def write_frame(self, df: pl.DataFrame, stage: str, name: str) -> list[str]:
        if df.is_empty():
            logger.info("Skipping empty frame %s/%s", stage, name)
            return []
        if "season" not in df.columns:
            return [self.put_parquet(df, self.key(stage, name))]

        uris: list[str] = []
        seasons = df.get_column("season").unique().drop_nulls().sort().to_list()
        for season in seasons:
            part = df.filter(pl.col("season") == season)
            uris.append(self.put_parquet(part, self.key(stage, name, season=int(season))))
        return uris
