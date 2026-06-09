"""TLC Yellow Taxi schema contract: rename + canonical Spark SQL types.

The DLT Silver projection (ADR-0001, ADR-0005) has two load-bearing
properties:

1. Every column from the TLC source is **renamed** to snake_case. Five
   of those names are part of the case statement contract
   (:data:`nyc_taxi_case.schema.REQUIRED_TLC_COLUMNS`); the other 14
   are kept because Silver is the "canonical" layer (ADR-0001) and
   because dropping them would invalidate the "Medallion real
   reutilizável" argument (ADR-0005).

2. Every column is **cast** to a canonical Spark SQL type. That makes
   the Silver table independent of TLC schema drift (e.g. ``Int64``
   widening, datetime arriving as STRING) and locks money columns to
   DECIMAL so EDA sums on ``total_amount`` do not accumulate float
   error.

This module is the single source of truth for both maps. It is
intentionally Spark-free so the DLT pipeline can call it from inside
``@dlt.table``-decorated functions while the tests run under plain
pytest in CI.

The 14 "ignored" columns come from ADR-0005 §Context (verbatim list).
The 5 required columns come from :data:`REQUIRED_TLC_COLUMNS`. Sum: 19,
which matches the TLC Yellow 2023 parquet schema as of the case scope
(Jan-May 2023). The pytest module enforces both the count and the
bijectivity of the rename.
"""

from __future__ import annotations

from collections.abc import Mapping

__all__ = [
    "TLC_COLUMN_TYPES",
    "TLC_RENAME_MAP",
    "UnknownTlcColumnError",
    "canonical_name",
    "canonical_type",
]


class UnknownTlcColumnError(KeyError):
    """Raised when a column name is neither a TLC source nor a renamed alias.

    Inherits from :class:`KeyError` so callers that already catch the
    stdlib exception (e.g. defensive ``except KeyError``) still work,
    while explicit ``except UnknownTlcColumnError`` lets the DLT layer
    surface the offending column name in pipeline logs.
    """


# --------------------------------------------------------------------------- #
# Rename map
# --------------------------------------------------------------------------- #
# Key   = column name as it arrives from the TLC parquet (post Auto Loader).
# Value = canonical snake_case name on the Silver table.
#
# Identity mappings (``tpep_pickup_datetime`` → ``tpep_pickup_datetime``)
# are listed explicitly rather than omitted: they document that the
# author considered the column and chose to keep the name. The pytest
# count check would otherwise pass spuriously if we silently dropped
# them.
TLC_RENAME_MAP: Mapping[str, str] = {
    # ---- 5 required by the case statement (REQUIRED_TLC_COLUMNS) ----
    "VendorID": "vendor_id",
    "tpep_pickup_datetime": "tpep_pickup_datetime",
    "tpep_dropoff_datetime": "tpep_dropoff_datetime",
    "passenger_count": "passenger_count",
    "total_amount": "total_amount",
    # ---- 14 listed as "ignored by case" in ADR-0005 §Context --------
    "trip_distance": "trip_distance",
    "RatecodeID": "ratecode_id",
    "store_and_fwd_flag": "store_and_fwd_flag",
    "PULocationID": "pu_location_id",
    "DOLocationID": "do_location_id",
    "payment_type": "payment_type",
    "fare_amount": "fare_amount",
    "extra": "extra",
    "mta_tax": "mta_tax",
    "tip_amount": "tip_amount",
    "tolls_amount": "tolls_amount",
    "improvement_surcharge": "improvement_surcharge",
    "congestion_surcharge": "congestion_surcharge",
    "airport_fee": "airport_fee",
}


# --------------------------------------------------------------------------- #
# Canonical Spark SQL types (post-rename)
# --------------------------------------------------------------------------- #
# Keys are the snake_case names from the rename map's values.
#
# Source-type reference (validated against yellow_tripdata_2023-01.parquet,
# 3,066,766 rows, 19 columns, schema in Arrow notation):
#
#   VendorID                -> int64
#   tpep_pickup_datetime    -> timestamp[us]
#   tpep_dropoff_datetime   -> timestamp[us]
#   passenger_count         -> double   (carries NULL; ints widened to double)
#   trip_distance           -> double
#   RatecodeID              -> double   (carries NULL; same widening)
#   store_and_fwd_flag      -> string
#   PULocationID            -> int64
#   DOLocationID            -> int64
#   payment_type            -> int64
#   fare_amount/extra/mta_tax/tip_amount/tolls_amount/
#     improvement_surcharge/total_amount/congestion_surcharge/
#     airport_fee           -> double
#
# Type rationale:
#
# * ``vendor_id`` / ``passenger_count`` / ``ratecode_id`` /
#   ``payment_type`` / ``pu_location_id`` / ``do_location_id`` are
#   BIGINT — the semantic type is integer in every case ("count of
#   passengers", "rate code id"). TLC ships some as ``double`` only
#   because pandas/Arrow widens NULL-bearing integer columns. CAST to
#   BIGINT in Silver round-trips cleanly (NULL stays NULL, no
#   fractional passenger_count exists in reality) and matches the dbt
#   `accepted_values` test on `vendor_id` (#09).
#
# * Datetimes are TIMESTAMP — explicit CAST makes the Silver projection
#   robust against a TLC schema surprise (e.g. STRING arriving in a
#   future month) without changing downstream consumers.
#
# * Money columns are DECIMAL(10, 2). Two scale digits cover cents; 10
#   precision covers four-digit-dollar fares with headroom. Float math
#   on money is a known footgun and the EDA sums ``total_amount``.
#
# * ``trip_distance`` is DOUBLE — it is float in the source and no EDA
#   does money-like sums on it. Forcing DECIMAL would require picking a
#   scale (TLC ships sub-mile precision) with no upside.
#
# * ``store_and_fwd_flag`` is STRING ("Y" / "N").
TLC_COLUMN_TYPES: Mapping[str, str] = {
    "vendor_id": "BIGINT",
    "tpep_pickup_datetime": "TIMESTAMP",
    "tpep_dropoff_datetime": "TIMESTAMP",
    "passenger_count": "BIGINT",
    "total_amount": "DECIMAL(10, 2)",
    "trip_distance": "DOUBLE",
    "ratecode_id": "BIGINT",
    "store_and_fwd_flag": "STRING",
    "pu_location_id": "BIGINT",
    "do_location_id": "BIGINT",
    "payment_type": "BIGINT",
    "fare_amount": "DECIMAL(10, 2)",
    "extra": "DECIMAL(10, 2)",
    "mta_tax": "DECIMAL(10, 2)",
    "tip_amount": "DECIMAL(10, 2)",
    "tolls_amount": "DECIMAL(10, 2)",
    "improvement_surcharge": "DECIMAL(10, 2)",
    "congestion_surcharge": "DECIMAL(10, 2)",
    "airport_fee": "DECIMAL(10, 2)",
}


# Precomputed set of canonical names for the idempotent ``canonical_name``
# behaviour. Built once at import time; tests pin its content.
_CANONICAL_NAMES: frozenset[str] = frozenset(TLC_RENAME_MAP.values())


def canonical_name(column: str) -> str:
    """Return the snake_case name for a TLC column.

    Tolerates already-canonical input (a refactor that wraps a
    snake_case column does not need to know whether it has already
    been renamed). Raises :class:`UnknownTlcColumnError` for anything
    else so a TLC schema addition surfaces loudly in the DLT logs
    rather than silently passing an unmapped name to Silver.
    """
    if column in TLC_RENAME_MAP:
        return TLC_RENAME_MAP[column]
    if column in _CANONICAL_NAMES:
        return column
    raise UnknownTlcColumnError(
        f"unknown TLC column {column!r}; not in TLC_RENAME_MAP nor among canonical snake_case names"
    )


def canonical_type(column: str) -> str:
    """Return the canonical Spark SQL type for a TLC column.

    Accepts either the TLC source name or the snake_case alias — the
    DLT projection may call this before or after renaming. Raises
    :class:`UnknownTlcColumnError` for unknown columns so an
    unvetted TLC addition surfaces loudly.
    """
    snake = canonical_name(column)
    return TLC_COLUMN_TYPES[snake]
