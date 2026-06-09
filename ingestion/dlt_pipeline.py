"""DLT pipeline — Bronze (Auto Loader) + Silver canonical for Yellow Taxi.

This file is intended to run as a Databricks **Lakeflow Declarative
Pipeline** (formerly Delta Live Tables / DLT). It owns two nodes:

* **Bronze** — ``${prefix}nyc_taxi_bronze.yellow_taxi_trips_raw``,
  a Streaming Table fed by Auto Loader. Preserves 100 % of the TLC
  columns plus three metadata columns. No rename, no cast, no drop.

* **Silver** — ``${prefix}nyc_taxi_silver.yellow_taxi_trips``,
  a Materialized View built from Bronze. Renames every TLC column to
  snake_case (via :mod:`nyc_taxi_case.tlc_schema`), casts each to a
  canonical Spark SQL type, and materialises two derived columns:

  * ``pickup_year_month`` — ``YYYY-MM`` of the pickup datetime
    (CONTEXT.md, ADR-0003).
  * ``file_year_month`` — ``YYYY-MM`` parsed from
    ``_metadata.file_path`` (ADR-0004).

  Layout is **Liquid Clustering** on ``pickup_year_month`` (ADR-0006),
  with defensive ``tblproperties`` for Free Edition quota (ADR-0005).

Both nodes carry **DLT expectations** (ticket #05, ADR-0007): 1 warn-only
on Bronze (schema contract — the 5 required columns must arrive non-null)
and 6 on Silver (4 ``expect_or_drop`` for case-answer integrity + 2
``expect`` warn for TLC drift signals). Zero ``expect_or_fail`` by ADR;
the rationale is in ``docs/adr/0007-expectations-sem-expect-or-fail.md``.

**Out of scope (later tickets):**

* The ``job_ingestion`` DAB that registers this pipeline + the
  ``UPDATE landing_audit SET pipeline_update_id`` SQL task — ticket #06.

**Spark parameter consumed (set in the pipeline definition #06):**

* ``landing_volume_path`` — Volume UC path the Bronze reads from.

The destination catalog / schema are *not* parameters of this file —
the DLT pipeline definition (ticket #06) sets ``catalog`` /
``target`` at the pipeline level and Lakeflow publishes the tables
there. Hard-wiring them here would create a second source of truth
that drifts from ``resources/general_variables.yml``.

The pipeline runs **standalone** via Databricks pipelines API or
``bundle run job_ingestion`` (the latter once #06 lands). It is
**not** unit-tested here — the helper that drives the rename/cast is
covered by ``ingestion/tests/test_tlc_schema.py``; the DLT decorators
require a Databricks runtime.
"""

# ruff: noqa: E402  # Databricks injects spark / dlt before user imports
# mypy: disable-error-code="import-untyped, misc"

from __future__ import annotations

from typing import TYPE_CHECKING

import dlt  # type: ignore[import-not-found]  # Databricks-provided
from pyspark.sql import functions as F  # noqa: N812

from nyc_taxi_case.schema import FILE_YEAR_MONTH_PATTERN, REQUIRED_TLC_COLUMNS
from nyc_taxi_case.tlc_schema import TLC_RENAME_MAP, canonical_type

# --------------------------------------------------------------------------- #
# DLT expectation rules
# --------------------------------------------------------------------------- #
# Ticket #05 / ADR-0007: 6 Silver + 1 Bronze warn, **zero expect_or_fail**.
# The contract is "fail soft + observe in event_log" — schema drift is caught
# pre-deploy by ``test_tlc_schema.py``/``test_schema.py``; this layer is the
# runtime safety net, never the gating mechanism.
#
# The Bronze rule is composed from ``REQUIRED_TLC_COLUMNS`` so a change in
# the case-required column list propagates here without manual edit (caught
# at PR time by the pytest contract test that ALSO reads that constant).

_BRONZE_REQUIRED_NOT_NULL_RULE: str = " AND ".join(f"{c} IS NOT NULL" for c in REQUIRED_TLC_COLUMNS)

if TYPE_CHECKING:  # pragma: no cover - type-only imports
    from pyspark.sql import DataFrame

# --------------------------------------------------------------------------- #
# Pipeline parameters
# --------------------------------------------------------------------------- #
# DLT exposes pipeline-level parameters through ``spark.conf.get``.
# Defaults mirror ``resources/general_variables.yml`` so the pipeline
# is runnable interactively for ad-hoc debugging.
spark = globals().get("spark")  # injected by the Databricks runtime


def _conf(key: str, default: str) -> str:
    """Return a pipeline parameter, falling back to ``default`` if unset."""
    if spark is None:  # pragma: no cover - import-time guard for pytest
        return default
    try:
        value: str = spark.conf.get(key, default)
    except Exception:  # noqa: BLE001 — defensive against runtime quirks
        return default
    return value or default


_LANDING_VOLUME_PATH = _conf(
    "landing_volume_path",
    "/Volumes/workspace/nyc_taxi_bronze/landing/yellow",
)


# --------------------------------------------------------------------------- #
# Bronze — Streaming Table fed by Auto Loader
# --------------------------------------------------------------------------- #
# Decision matrix for the Auto Loader options:
#
# * ``format = parquet`` — TLC ships parquet.
# * ``schemaEvolutionMode = addNewColumns`` — TLC has added columns
#   silently in the past (ADR-0007: ``airport_fee`` showed up in 2022).
#   ``addNewColumns`` materialises new columns on Bronze; the Silver
#   projection ignores anything not in ``TLC_RENAME_MAP``, so a TLC
#   addition is loud (Bronze schema diff) but not pipeline-breaking.
# * ``trigger = AvailableNow`` — single-shot batch over whatever the
#   Landing notebook deposited; the DAB triggers this pipeline only
#   after the landing notebook finishes (#06). No long-running stream.


@dlt.table(  # type: ignore[misc]
    name="yellow_taxi_trips_raw",
    comment=(
        "Bronze: raw TLC Yellow Taxi parquets ingested via Auto Loader. "
        "Preserves 100% of source columns; adds Auto Loader metadata "
        "(_metadata.file_path / _metadata.file_modification_time) and "
        "_ingestion_ts. No rename, no cast, no drop (ADR-0001)."
    ),
    table_properties={
        # Bronze is append-only (Streaming Table), no autoOptimize needed.
        # The properties below help SQL Warehouse listing perf without
        # changing the streaming semantics.
        "delta.autoOptimize.optimizeWrite": "true",
        "delta.autoOptimize.autoCompact": "true",
    },
)
# Expectation #7-bronze (ADR-0007): warn-only schema contract — the 5 columns
# the case statement requires must arrive non-null. ``expect`` (not
# ``expect_or_drop`` / ``expect_or_fail``) so a TLC rename surfaces in
# event_log without aborting Bronze. The rule itself is sourced from
# ``REQUIRED_TLC_COLUMNS`` (same constant the pytest contract reads).
@dlt.expect("bronze_required_columns_not_null", _BRONZE_REQUIRED_NOT_NULL_RULE)  # type: ignore[misc]
def yellow_taxi_trips_raw() -> DataFrame:
    """Bronze Streaming Table — TLC parquets via Auto Loader.

    The DLT decorator publishes this under
    ``${catalog}.${bronze_schema}.yellow_taxi_trips_raw``. Schema is
    inferred from the first parquet; subsequent files may add columns
    (``schemaEvolutionMode = addNewColumns``) — when they do, the
    Silver projection's ``TLC_RENAME_MAP`` decides whether they
    propagate.

    The ``_metadata.file_modification_time`` column (column-level,
    not ``cloudFiles`` option) is added by Auto Loader by default in
    DBR 14+; we surface it explicitly so the Silver projection can
    rely on it without re-reading the source.
    """
    if spark is None:  # pragma: no cover - defensive for static analysis
        raise RuntimeError("Spark session not available — run inside DLT")

    reader = (
        spark.readStream.format("cloudFiles")
        .option("cloudFiles.format", "parquet")
        .option("cloudFiles.schemaEvolutionMode", "addNewColumns")
        # Inferring column types from parquet directly (vs sampling) is
        # safe here: parquet carries the schema in the footer.
        .option("cloudFiles.inferColumnTypes", "true")
    )
    return (
        reader.load(_LANDING_VOLUME_PATH)
        # ``_metadata`` is a hidden struct column Auto Loader exposes;
        # selecting it explicitly persists the metadata on the Bronze
        # table so Silver can read ``file_path`` without a Bronze
        # re-scan against the Volume.
        .select(
            "*",
            F.col("_metadata.file_path").alias("_source_file_path"),
            F.col("_metadata.file_modification_time").alias("_source_file_modification_time"),
            F.current_timestamp().alias("_ingestion_ts"),
        )
    )


# --------------------------------------------------------------------------- #
# Silver — Materialized View, canonical and typed
# --------------------------------------------------------------------------- #
# The Silver projection is built dynamically from ``TLC_RENAME_MAP`` /
# ``canonical_type`` so a TLC schema change only requires editing the
# helper (caught at PR time by ``test_tlc_schema.py``).
#
# Liquid Clustering on ``pickup_year_month`` (ADR-0006) replaces the
# legacy ``PARTITIONED BY`` plan. Fallback documented in ADR-0006: if
# the Free Edition DLT runtime rejects the ``cluster_by`` arg, switch
# to ``partition_cols=["pickup_year_month"]`` and supersede the ADR.


def _build_silver_projection(bronze: DataFrame) -> DataFrame:
    """Return the canonical Silver DataFrame from a Bronze DataFrame.

    Extracted as a pure function (Spark API only — no decorators, no
    table publishing) so the logic is reviewable in isolation. The
    DLT-decorated ``yellow_taxi_trips`` wraps this with the
    ``@dlt.table`` machinery.

    For every TLC column in ``TLC_RENAME_MAP``:

    1. Project ``CAST(source_column AS <canonical_type>)``.
    2. Alias to the snake_case name.

    Then append the two derived columns and the Auto Loader metadata
    aliases the Bronze stage already promoted.
    """
    projection = [
        F.col(source).cast(canonical_type(source)).alias(target)
        for source, target in TLC_RENAME_MAP.items()
    ]
    return bronze.select(
        *projection,
        # pickup_year_month: derived from the (already cast) timestamp.
        # date_format on a TIMESTAMP yields a STRING in the requested
        # mask — matches CONTEXT.md ``pickup_year_month`` STRING ``YYYY-MM``.
        F.date_format(
            F.col("tpep_pickup_datetime").cast("TIMESTAMP"),
            "yyyy-MM",
        ).alias("pickup_year_month"),
        # file_year_month: ADR-0004. Single regex source-of-truth lives
        # in ``nyc_taxi_case.schema.FILE_YEAR_MONTH_PATTERN``; we reuse
        # its string form here so a refactor of the helper propagates.
        F.regexp_extract(
            F.col("_source_file_path"),
            FILE_YEAR_MONTH_PATTERN.pattern,
            1,
        ).alias("file_year_month"),
        # Propagate the Bronze metadata for audit/debug from Silver SQL.
        F.col("_source_file_path"),
        F.col("_source_file_modification_time"),
        F.col("_ingestion_ts"),
    )


@dlt.table(  # type: ignore[misc]
    name="yellow_taxi_trips",
    comment=(
        "Silver: TLC Yellow Taxi canonical and typed (ADR-0001). All 19 "
        "TLC columns renamed to snake_case and cast to canonical Spark "
        "SQL types; pickup_year_month (ADR-0003) and file_year_month "
        "(ADR-0004) materialised. Liquid Clustering on pickup_year_month "
        "(ADR-0006). 6 expectations applied (#05 / ADR-0007): 4 drop + "
        "2 warn; zero expect_or_fail."
    ),
    cluster_by=["pickup_year_month"],
    table_properties={
        # ADR-0005 defensive properties for Free Edition quota. ZSTD
        # level cannot be overridden via tblproperties on DLT-managed
        # tables; the autoOptimize/autoCompact pair plus tuneFileSizesForRewrites
        # is what actually moves the needle. The README cites this trade-off.
        "delta.autoOptimize.optimizeWrite": "true",
        "delta.autoOptimize.autoCompact": "true",
        "delta.tuneFileSizesForRewrites": "true",
    },
)
# Silver expectations (ticket #05, ADR-0007). Grouped by severity:
#
# * ``expect_all_or_drop`` — rules #2-5: filter rows whose values would
#   skew the case answers (refunds, impossible passenger counts, NULL or
#   inverted timestamps). The dropped count surfaces in event_log so the
#   pipeline observability view (ticket #13) can chart it.
# * ``expect_all`` (warn) — rules #1 and #6a: TLC drift signals that do
#   NOT corrupt downstream answers (unknown vendor_id stays in Silver;
#   the dbt ``accepted_values`` test gates it before Gold). #6a surfaces
#   TLC's known temporal noise (pickups dated 2001/2087 in 2023 files)
#   per ADR-0003 — Silver preserves, Gold filters by the window.
#
# Rules use the *Silver* column names (post-rename) because expectations
# evaluate against the table's projection, not its inputs. Reminder
# from #04: ``passenger_count`` arrives as DOUBLE in the source (Arrow
# widens NULL-bearing int cols) and is CAST to BIGINT in Silver — rule
# #2 operates on the canonicalised BIGINT, not the raw DOUBLE.
@dlt.expect_all_or_drop(  # type: ignore[misc]
    {
        "passenger_count_in_range": "passenger_count BETWEEN 0 AND 9",
        "total_amount_non_negative": "total_amount >= 0",
        "trip_timestamps_not_null": (
            "tpep_pickup_datetime IS NOT NULL AND tpep_dropoff_datetime IS NOT NULL"
        ),
        "dropoff_after_pickup": "tpep_dropoff_datetime >= tpep_pickup_datetime",
    }
)
@dlt.expect_all(  # type: ignore[misc]
    {
        "vendor_id_in_dictionary": "vendor_id IN (1, 2, 6, 7)",
        "pickup_month_matches_file": "pickup_year_month = file_year_month",
    }
)
def yellow_taxi_trips() -> DataFrame:
    """Silver Materialized View — canonical, typed Yellow Taxi trips.

    Reads the Bronze Streaming Table via ``dlt.read``. The projection
    is built from :data:`TLC_RENAME_MAP` / :func:`canonical_type` so
    schema drift in TLC surfaces at the helper boundary (caught by
    ``test_tlc_schema.py``) instead of as a runtime cast failure.
    """
    if spark is None:  # pragma: no cover - defensive for static analysis
        raise RuntimeError("Spark session not available — run inside DLT")
    bronze = dlt.read("yellow_taxi_trips_raw")
    return _build_silver_projection(bronze)
