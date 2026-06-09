"""TLC CloudFront URL builder for NYC Yellow Taxi parquet files.

The TLC publishes monthly trip data parquets at a CloudFront origin.
The exact base URL and the ``yellow_tripdata_YYYY-MM.parquet`` naming
convention were empirically validated by the dbt_task probe on
2026-06-08 (HEAD request returned STATUS=200 in 0.10s). See
``docs/adr/0010-fronteira-ingestao-modelagem-na-silver.md`` §Validação
empírica.

Keeping this builder Spark-free lets ``ingestion/tests/`` exercise it
in plain pytest with zero Databricks runtime dependency.
"""

from __future__ import annotations

from nyc_taxi_case.window import InvalidYearMonthError, parse_year_month

__all__ = [
    "InvalidYearMonthError",
    "TLC_CLOUDFRONT_BASE",
    "build_yellow_taxi_url",
]

#: Base path for TLC monthly trip-data parquets. Do not append a trailing
#: slash here — :func:`build_yellow_taxi_url` joins explicitly.
TLC_CLOUDFRONT_BASE: str = "https://d37ci6vzurychx.cloudfront.net/trip-data"


def build_yellow_taxi_url(year_month: str) -> str:
    """Return the canonical TLC URL for a Yellow Taxi monthly parquet.

    Args:
        year_month: Canonical ``YYYY-MM`` form. Parsed (not just regex-matched)
            via :func:`nyc_taxi_case.window.parse_year_month` to keep
            validation rules in a single place.

    Raises:
        InvalidYearMonthError: ``year_month`` is not canonical ``YYYY-MM``.
    """
    # parse_year_month raises InvalidYearMonthError on malformed input;
    # we re-export the type at module level so callers do not have to
    # know about the window module.
    parse_year_month(year_month)
    return f"{TLC_CLOUDFRONT_BASE}/yellow_tripdata_{year_month}.parquet"
