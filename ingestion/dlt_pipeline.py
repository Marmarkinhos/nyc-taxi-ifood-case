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
from nyc_taxi_case.tlc_schema import TLC_RENAME_MAP, bronze_schema_hints, canonical_type

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
        # ADR-0013: TLC Yellow parquets declare tpep_pickup_datetime /
        # tpep_dropoff_datetime as TIMESTAMP_NTZ (no timezone). Auto
        # Loader's inferColumnTypes preserves that, but Delta on Free
        # Edition does not enable the ``timestampNtz`` table feature
        # by default — first write fails with
        # DELTA_FEATURES_REQUIRE_MANUAL_ENABLEMENT. Enabling the
        # feature here keeps the Bronze fiel-à-fonte (ADR-0001) and is
        # the runtime equivalent of the autoOptimize flags above
        # (configuração de runtime, não transformação semântica).
        "delta.feature.timestampNtz": "supported",
        # ADR-0015: enable Delta type widening so the reader's
        # ``addNewColumnsWithTypeWidening`` mode can widen narrow
        # source types (e.g. INT32 → INT64) into the existing column
        # type without rewriting data. Prereq per Databricks docs:
        # https://docs.databricks.com/aws/en/ingestion/cloud-object-storage/auto-loader/type-widening#prerequisites
        # Without this, the 3 INT-width-drifting columns (VendorID /
        # PULocationID / DOLocationID) would still rescue.
        "delta.enableTypeWidening": "true",
    },
)
# Expectation #7-bronze (ADR-0007): warn-only schema contract — the 5 columns
# the case statement requires must arrive non-null. ``expect`` (not
# ``expect_or_drop`` / ``expect_or_fail``) so a TLC rename surfaces in
# event_log without aborting Bronze. The rule itself is sourced from
# ``REQUIRED_TLC_COLUMNS`` (same constant the pytest contract reads).
@dlt.expect("bronze_required_columns_not_null", _BRONZE_REQUIRED_NOT_NULL_RULE)  # type: ignore[misc]
# Expectation #8-bronze (ADR-0014): warn-only drift detector for the
# Auto Loader rescue column. With ``cloudFiles.schemaHints`` anchoring
# the 19 TLC columns (Fix #7), ``_rescued_data`` should be NULL on every
# row. Any non-NULL value means either (a) TLC introduced a 20th column
# the helper does not know about, or (b) a TLC dtype/name drifted past
# what the hints can absorb. The expectation makes both visible in
# ``event_log`` without breaking the pipeline — drop/fail would shoot
# the messenger (see ADR-0007: the schema-drift signal is more valuable
# than the rows it taints). The percentage of failed records is the
# load-bearing metric; ticket #14 lifts it to job-level alerting.
@dlt.expect("bronze_no_rescued_data", "_rescued_data IS NULL")  # type: ignore[misc]
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
        # ADR-0015: switch from ``addNewColumns`` to
        # ``addNewColumnsWithTypeWidening``. The latter widens supported
        # data types automatically (e.g. INT32→INT64, INT64→DOUBLE)
        # without rescuing the row group. This is load-bearing for the
        # TLC 2023 dataset: feb-mai ships 5 columns at narrower types
        # than jan (VendorID/PULocationID/DOLocationID INT64→INT32,
        # passenger_count/RatecodeID DOUBLE→INT64). Without widening,
        # those 5 columns trigger ``_rescued_data IS NOT NULL`` on
        # 100 % of feb-mai rows.
        # https://docs.databricks.com/aws/en/ingestion/cloud-object-storage/auto-loader/type-widening
        .option("cloudFiles.schemaEvolutionMode", "addNewColumnsWithTypeWidening")
        # Inferring column types from parquet directly (vs sampling) is
        # safe here: parquet carries the schema in the footer.
        .option("cloudFiles.inferColumnTypes", "true")
        # ADR-0015 (supersedes ADR-0014): anchor name + source-side
        # type for the 14 TLC columns that have NOT drifted across
        # jan-mai 2023. The 5 type-drifting columns (VendorID,
        # passenger_count, RatecodeID, PULocationID, DOLocationID)
        # are deliberately NOT hinted — they would block the type
        # widening above. See ``BRONZE_SCHEMA_HINT_TYPES`` docstring
        # for the full empirical drift table.
        .option("cloudFiles.schemaHints", bronze_schema_hints())
        # ADR-0014 follow-up correction (Fix #8): hints anchor the
        # canonical name (``airport_fee``) but the parquet reader's
        # default ``readerCaseSensitive=true`` still sends case-different
        # source fields (``Airport_fee`` in TLC feb–mai/2023) to
        # ``_rescued_data``. The Databricks docs name this exact
        # behaviour and the exact escape hatch:
        # https://docs.databricks.com/aws/en/ingestion/cloud-object-storage/auto-loader/schema#change-case-sensitive-behavior
        # Note: ``readerCaseSensitive`` is a **format-specific**
        # DataFrameReader option (per Spark API reference §Parquet),
        # NOT a ``cloudFiles.*`` option — Auto Loader rejects the
        # ``cloudFiles.readerCaseSensitive`` form with
        # ``CF_UNKNOWN_OPTION_KEYS_ERROR``. Setting it to ``false``
        # makes the parquet reader resolve fields case-insensitively
        # against the hint-anchored schema, so ``Airport_fee`` reads
        # INTO ``airport_fee`` instead of rescuing the whole row
        # group. This anchoring still matters under ADR-0015 because
        # the case drift is not a type-class drift and would not be
        # solved by type widening alone.
        .option("readerCaseSensitive", "false")
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

    The two columns ``passenger_count`` and ``RatecodeID`` are special
    (ADR-0015): TLC drifted their physical type from DOUBLE (jan/2023)
    to INT64 (feb-mai/2023). The Auto Loader type-widening table only
    widens ``long → decimal`` and has no path for ``long → double``,
    so feb-mai rows land with the typed column NULL and the original
    integer value in ``_rescued_data``. This projection recovers them
    via ``coalesce(typed_col, get_json_object(_rescued_data, ...))``
    so the downstream ``passenger_count BETWEEN 0 AND 9`` expectation
    sees the real value, not NULL.

    Then append the two derived columns and the Auto Loader metadata
    aliases the Bronze stage already promoted.
    """
    # ADR-0015 type-drift recovery: 2 columns that Auto Loader cannot
    # widen across jan↔feb-mai 2023. Map: source name → JSON path used
    # by ``get_json_object``. The recovered value is cast to the same
    # canonical type the projection would have produced (BIGINT for
    # both — see TLC_COLUMN_TYPES in nyc_taxi_case.tlc_schema).
    _RESCUED_RECOVERY: dict[str, str] = {
        "passenger_count": "$.passenger_count",
        "RatecodeID": "$.RatecodeID",
    }

    def _project(source: str, target: str) -> F.Column:
        cast_type = canonical_type(source)
        typed = F.col(source).cast(cast_type)
        if source in _RESCUED_RECOVERY:
            # The rescued value is a JSON number; ``get_json_object``
            # returns it as STRING which we cast to the canonical type.
            # ``coalesce`` keeps the typed col when non-NULL (jan path)
            # and falls back to the rescued value otherwise (feb-mai).
            recovered = F.get_json_object(F.col("_rescued_data"), _RESCUED_RECOVERY[source]).cast(
                cast_type
            )
            return F.coalesce(typed, recovered).alias(target)
        return typed.alias(target)

    projection = [_project(source, target) for source, target in TLC_RENAME_MAP.items()]
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
        # ADR-0013: defensive enable of timestampNtz feature. The Silver
        # projection casts tpep_*_datetime to TIMESTAMP-com-tz (see
        # ``canonical_type`` in nyc_taxi_case.tlc_schema), so the
        # current Silver schema does not need this flag. We enable it
        # anyway to (a) match the Bronze contract symmetrically and
        # (b) survive a future TLC addition of a NTZ column that the
        # Silver projection forwards verbatim.
        "delta.feature.timestampNtz": "supported",
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
