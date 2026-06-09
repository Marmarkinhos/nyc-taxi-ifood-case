"""Tests for the TLC Yellow Taxi schema contract helper.

This module is the gate that catches drift between what the case
statement / ADRs declare and what we hand-code into the DLT pipeline.
It runs Spark-free in CI so a mismatch surfaces at PR review time, not
at midnight on a Databricks job.

Coverage targets (each one corresponds to a load-bearing claim made
elsewhere in the repo):

* All 19 TLC Yellow 2023 columns are mapped (CONTEXT.md "Silver",
  ADR-0005 lists the 14 "ignored" ones; the 5 required come from
  ``REQUIRED_TLC_COLUMNS`` in :mod:`nyc_taxi_case.schema`).
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

from nyc_taxi_case.schema import REQUIRED_TLC_COLUMNS
from nyc_taxi_case.tlc_schema import (
    TLC_COLUMN_TYPES,
    TLC_RENAME_MAP,
    UnknownTlcColumnError,
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
