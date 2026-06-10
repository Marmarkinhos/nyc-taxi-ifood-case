"""Tests for the TLC Yellow Taxi schema contract helper.

This module is the gate that catches drift between what the case
statement / ADRs declare and what we hand-code into the DLT pipeline.
It runs Spark-free in CI so a mismatch surfaces at PR review time, not
at midnight on a Databricks job.

Coverage targets (each one corresponds to a load-bearing claim made
elsewhere in the repo):

* All 19 TLC Yellow 2023 columns are mapped (CONTEXT.md "Silver",
  ADR-0005 lists the 14 "ignored" ones; the 5 required come from
  ``REQUIRED_TLC_COLUMNS`` in :mod:`nyc_taxi_case.case_contract`).
* The rename map is bijective: no two TLC columns collapse onto the
  same snake_case name (a regression here silently drops data).
* Every TLC column gets a Spark SQL type so the Silver projection
  never falls back to inferred / string types.
* The 5 ``REQUIRED_TLC_COLUMNS`` are all present in the rename map —
  guarantees the case-mandated columns survive the Silver transform.
* ``tpep_pickup_datetime`` / ``tpep_dropoff_datetime`` map to
  themselves (they are already snake_case in the source).
* The rename helper is idempotent for already-snake_case columns.
"""

from __future__ import annotations

import pytest

from nyc_taxi_case.case_contract import REQUIRED_TLC_COLUMNS
from nyc_taxi_case.tlc_schema import (
    BRONZE_SCHEMA_HINT_TYPES,
    TLC_COLUMN_TYPES,
    TLC_RENAME_MAP,
    UnknownTlcColumnError,
    bronze_schema_hints,
    canonical_name,
    canonical_type,
)


class TestRenameMap:
    """Coverage of the 19-column rename contract."""

    def test_has_exactly_nineteen_columns(self) -> None:
        # TLC Yellow 2023 parquet ships 19 columns. A change here means
        # either TLC altered the schema (then update the map + ADR) or
        # we miscounted (then fix the map). Either way it must be loud.
        assert len(TLC_RENAME_MAP) == 19, (
            f"expected 19 TLC columns, got {len(TLC_RENAME_MAP)}: {sorted(TLC_RENAME_MAP)}"
        )

    def test_is_bijective(self) -> None:
        # Two TLC columns collapsing onto the same snake_case name
        # would silently drop a column. Catch it pre-deploy.
        snake_names = list(TLC_RENAME_MAP.values())
        assert len(set(snake_names)) == len(snake_names), (
            f"rename map collisions: {[n for n in snake_names if snake_names.count(n) > 1]}"
        )

    def test_covers_all_required_case_columns(self) -> None:
        # The case statement (docs/CASE.md) names these 5; if any is
        # missing from the rename map, the Silver projection will drop
        # it and the Gold model will fail.
        missing = [c for c in REQUIRED_TLC_COLUMNS if c not in TLC_RENAME_MAP]
        assert not missing, f"required TLC columns absent from rename map: {missing}"

    def test_tpep_datetimes_are_self_mapped(self) -> None:
        # Datetimes are already snake_case in the TLC source; mapping
        # them to anything else would break downstream expectations
        # (#04 derives `pickup_year_month` from `tpep_pickup_datetime`).
        assert TLC_RENAME_MAP["tpep_pickup_datetime"] == "tpep_pickup_datetime"
        assert TLC_RENAME_MAP["tpep_dropoff_datetime"] == "tpep_dropoff_datetime"

    def test_covers_adr0005_listed_ignored_columns(self) -> None:
        # ADR-0005 enumerates the 14 columns the case says "can be
        # ignored". Silver preserves them anyway (ADR-0001) — so they
        # MUST be in the rename map.
        adr0005_ignored = [
            "payment_type",
            "RatecodeID",
            "store_and_fwd_flag",
            "PULocationID",
            "DOLocationID",
            "fare_amount",
            "extra",
            "mta_tax",
            "tip_amount",
            "tolls_amount",
            "improvement_surcharge",
            "congestion_surcharge",
            "airport_fee",
            "trip_distance",
        ]
        missing = [c for c in adr0005_ignored if c not in TLC_RENAME_MAP]
        assert not missing, f"ADR-0005 columns missing from rename map: {missing}"


class TestTypeMap:
    """Coverage of the canonical Spark SQL type contract."""

    def test_every_renamed_column_has_a_type(self) -> None:
        # Silver projects via SELECT CAST(col AS <type>) AS new_name —
        # a missing type means falling back to source-inferred type,
        # which defeats the "canonical and typed" property of ADR-0001.
        snake_columns = set(TLC_RENAME_MAP.values())
        typed_columns = set(TLC_COLUMN_TYPES)
        missing = snake_columns - typed_columns
        assert not missing, f"snake_case columns missing canonical type: {sorted(missing)}"

    def test_no_extra_types_without_source(self) -> None:
        # Symmetric check: a type for a column we do not rename is dead
        # code at best, a typo at worst.
        snake_columns = set(TLC_RENAME_MAP.values())
        typed_columns = set(TLC_COLUMN_TYPES)
        extra = typed_columns - snake_columns
        assert not extra, f"types declared for non-existent columns: {sorted(extra)}"

    def test_monetary_columns_are_decimal(self) -> None:
        # Floating-point on money is a known footgun; the case statement
        # asks for `total_amount` end-to-end and the EDA may sum it.
        # DECIMAL avoids cumulative rounding error.
        monetary = [
            "total_amount",
            "fare_amount",
            "tip_amount",
            "tolls_amount",
            "extra",
            "mta_tax",
            "improvement_surcharge",
            "congestion_surcharge",
            "airport_fee",
        ]
        for col in monetary:
            assert TLC_COLUMN_TYPES[col].upper().startswith("DECIMAL"), (
                f"{col} should be DECIMAL, got {TLC_COLUMN_TYPES[col]!r}"
            )

    def test_datetimes_are_timestamp(self) -> None:
        # Auto Loader / Parquet brings these as TIMESTAMP already, but
        # the Silver CAST makes it explicit and survives a schema
        # surprise (e.g. TLC switching to STRING in a future month).
        for col in ("tpep_pickup_datetime", "tpep_dropoff_datetime"):
            assert TLC_COLUMN_TYPES[col].upper() == "TIMESTAMP", (
                f"{col} should be TIMESTAMP, got {TLC_COLUMN_TYPES[col]!r}"
            )

    def test_trip_distance_is_double(self) -> None:
        # Distance is float in the source; DECIMAL would force a scale
        # decision that adds no value (no money math depends on it).
        assert TLC_COLUMN_TYPES["trip_distance"].upper() == "DOUBLE"

    def test_passenger_count_is_long(self) -> None:
        # passenger_count arrives as DOUBLE in TLC parquets
        # (Arrow widens NULL-bearing integer columns), but the
        # *semantic* type is integer — there is no fractional
        # passenger_count in reality. CAST to BIGINT in Silver
        # round-trips cleanly (NULL stays NULL) and matches the
        # downstream dbt tests on integer-typed counts.
        assert TLC_COLUMN_TYPES["passenger_count"].upper() == "BIGINT"

    def test_integer_ids_widened_in_source_are_canonicalised_to_bigint(self) -> None:
        # Empirical fact (yellow_tripdata_2023-01.parquet, 3.06M rows):
        # ``RatecodeID`` arrives as ``double`` in the source because TLC
        # has NULL ratecodes and pandas/Arrow widens integer columns
        # with NULL to double. The canonical Silver type is still
        # BIGINT — this CAST is the load-bearing reason the helper
        # exists. Pin it so a "let's just trust the source" refactor
        # does not silently revert to DOUBLE.
        assert TLC_COLUMN_TYPES["ratecode_id"].upper() == "BIGINT"


class TestCanonicalHelpers:
    """Coverage of the small Spark-free wrappers used by the DLT code."""

    def test_canonical_name_translates_known_columns(self) -> None:
        # The helper exists so the DLT pipeline does not hard-code
        # dictionary lookups inline.
        assert canonical_name("VendorID") == "vendor_id"
        assert canonical_name("tpep_pickup_datetime") == "tpep_pickup_datetime"

    def test_canonical_name_is_idempotent_on_already_renamed(self) -> None:
        # Defensive: calling `canonical_name` twice (e.g. a refactor
        # that wraps an already-snake_case column) must not raise.
        assert canonical_name("vendor_id") == "vendor_id"

    def test_canonical_name_rejects_unknown_columns(self) -> None:
        # If TLC adds a column we have not vetted, the DLT pipeline
        # must surface it loudly (caller wraps the call) rather than
        # silently passing through an unmapped name.
        with pytest.raises(UnknownTlcColumnError) as exc:
            canonical_name("MysteryColumn")
        assert "MysteryColumn" in str(exc.value)

    def test_canonical_type_translates_known_columns(self) -> None:
        assert canonical_type("total_amount").upper().startswith("DECIMAL")
        assert canonical_type("tpep_pickup_datetime").upper() == "TIMESTAMP"

    def test_canonical_type_rejects_unknown_columns(self) -> None:
        with pytest.raises(UnknownTlcColumnError) as exc:
            canonical_type("MysteryColumn")
        assert "MysteryColumn" in str(exc.value)


# ADR-0015: the 5 columns TLC drifts on between jan and feb-mai 2023.
# These are deliberately EXCLUDED from BRONZE_SCHEMA_HINT_TYPES so Auto
# Loader's ``addNewColumnsWithTypeWidening`` evolution mode can widen
# their physical types (INT32→INT64, INT64→DOUBLE) instead of rescuing
# the row group. Pinned here so a refactor that "completes the hint
# map" surfaces loudly as a regression instead of silently re-enabling
# the rescue cascade. Verified empirically via pyarrow against the 5
# TLC public parquets (see ADR-0015 §Evidence).
_TYPE_DRIFTING_TLC_COLUMNS: frozenset[str] = frozenset(
    {
        "VendorID",  # jan=INT64, feb-mai=INT32
        "passenger_count",  # jan=DOUBLE, feb-mai=INT64
        "RatecodeID",  # jan=DOUBLE, feb-mai=INT64
        "PULocationID",  # jan=INT64, feb-mai=INT32
        "DOLocationID",  # jan=INT64, feb-mai=INT32
    }
)


class TestBronzeSchemaHints:
    """Coverage of the Auto Loader ``cloudFiles.schemaHints`` contract.

    ADR-0015 (supersedes ADR-0014): the Bronze reader pins name + type
    only for the 14 TLC columns that have NOT drifted across jan-mai
    2023. The 5 type-drifting columns must NOT be hinted — hinting them
    would re-enable the rescue cascade ADR-0015 was written to remove.
    """

    def test_hint_types_cover_every_stable_renamed_column(self) -> None:
        # Every TLC column that is NOT in the type-drifting set must
        # appear in BRONZE_SCHEMA_HINT_TYPES. This catches a future
        # contributor accidentally dropping a hint for a stable column
        # (which would weaken the schema-drift safety net).
        rename_keys = set(TLC_RENAME_MAP)
        hint_keys = set(BRONZE_SCHEMA_HINT_TYPES)
        expected_hinted = rename_keys - _TYPE_DRIFTING_TLC_COLUMNS
        missing = expected_hinted - hint_keys
        extra = hint_keys - expected_hinted
        assert not missing, f"BRONZE_SCHEMA_HINT_TYPES is missing stable columns: {sorted(missing)}"
        assert not extra, (
            f"BRONZE_SCHEMA_HINT_TYPES has unexpected keys (typo, or a "
            f"drifting column re-hinted by accident): {sorted(extra)}"
        )

    def test_drifting_columns_are_not_hinted(self) -> None:
        # ADR-0015 load-bearing assertion: re-hinting any of these 5
        # columns disables type widening on that column and reverts to
        # the pre-fix 100 % rescue rate on feb-mai 2023.
        hint_keys = set(BRONZE_SCHEMA_HINT_TYPES)
        regressed = _TYPE_DRIFTING_TLC_COLUMNS & hint_keys
        assert not regressed, (
            f"ADR-0015 regression: type-drifting TLC columns were re-added "
            f"to BRONZE_SCHEMA_HINT_TYPES, which will mass-rescue feb-mai "
            f"2023 rows: {sorted(regressed)}"
        )

    def test_silver_still_canonicalises_drifting_columns(self) -> None:
        # The 5 drifting columns are not hinted at Bronze, but they
        # STILL need a canonical Silver type — the rename + cast happens
        # in ``_build_silver_projection`` regardless of whether Bronze
        # had a hint. This guards against a refactor that drops both
        # the hint AND the canonical type.
        for source_col in _TYPE_DRIFTING_TLC_COLUMNS:
            snake = TLC_RENAME_MAP[source_col]
            assert snake in TLC_COLUMN_TYPES, (
                f"{source_col!r} is type-drifting (not hinted) AND missing "
                f"a canonical Silver type {snake!r}: drift won't be "
                f"normalised anywhere"
            )

    def test_hint_types_use_source_side_types_not_canonical(self) -> None:
        # Stable money columns are DOUBLE in the source parquet. The
        # Silver canonical type for monetary cols is DECIMAL(10,2) —
        # Bronze hints must reflect the source so the schemaHints does
        # not get reinterpreted as a cast (which would violate
        # ADR-0001).
        assert BRONZE_SCHEMA_HINT_TYPES["total_amount"] == "DOUBLE"
        assert BRONZE_SCHEMA_HINT_TYPES["fare_amount"] == "DOUBLE"
        # Silver canonical for the same columns is DECIMAL — proves
        # the Bronze ≠ Silver type distinction is intentional.
        assert TLC_COLUMN_TYPES["total_amount"].startswith("DECIMAL")
        assert TLC_COLUMN_TYPES["fare_amount"].startswith("DECIMAL")

    def test_hint_types_use_timestamp_ntz_for_tpep_datetimes(self) -> None:
        # Source parquet declares timestamp[us] (no timezone). The
        # hint must use TIMESTAMP_NTZ to match — otherwise Auto Loader
        # tries an implicit cast and the timestampNtz feature flag
        # (ADR-0013) becomes useless.
        assert BRONZE_SCHEMA_HINT_TYPES["tpep_pickup_datetime"] == "TIMESTAMP_NTZ"
        assert BRONZE_SCHEMA_HINT_TYPES["tpep_dropoff_datetime"] == "TIMESTAMP_NTZ"

    def test_hint_string_is_ddl_formatted(self) -> None:
        # cloudFiles.schemaHints accepts a comma-separated "name type"
        # list. Smoke-test the format: 14 entries (19 TLC cols minus 5
        # drifting), no leading/trailing whitespace surprises, each
        # entry has exactly one space.
        hints = bronze_schema_hints()
        entries = [e.strip() for e in hints.split(",")]
        expected_count = len(TLC_RENAME_MAP) - len(_TYPE_DRIFTING_TLC_COLUMNS)
        assert len(entries) == expected_count, (
            f"expected {expected_count} entries (19 TLC cols minus 5 drifting), got {len(entries)}"
        )
        for entry in entries:
            parts = entry.split(" ")
            assert len(parts) == 2, f"entry {entry!r} is not 'name type'"
            name, dtype = parts
            assert name in BRONZE_SCHEMA_HINT_TYPES
            assert dtype == BRONZE_SCHEMA_HINT_TYPES[name]

    def test_hint_string_contains_airport_fee_lowercase(self) -> None:
        # The single most important assertion in this whole file:
        # TLC's 2023-02 rename of airport_fee → Airport_fee was the
        # original motivation for ADR-0014's hint anchoring. ADR-0015
        # supersedes ADR-0014 for type drift, but airport_fee's case
        # drift is NOT a type-class drift and is still resolved by
        # this hint + readerCaseSensitive=false. By pinning the
        # lowercase form here, both jan/2023 (airport_fee) and
        # feb-mai/2023 (Airport_fee) resolve to the same Bronze
        # column instead of mass-rescuing.
        hints = bronze_schema_hints()
        assert "airport_fee DOUBLE" in hints
        # The CamelCase form must NOT appear — that would defeat the fix.
        assert "Airport_fee" not in hints
