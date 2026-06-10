"""Tests for nyc_taxi_case.case_contract — case schema contract and filename regex.

Contract (case statement, 5 required columns on Silver/Gold):
- VendorID
- passenger_count
- total_amount
- tpep_pickup_datetime
- tpep_dropoff_datetime

This module also owns the regex that extracts file_year_month from
TLC parquet filenames (ADR-0004 / CONTEXT.md "file_year_month").
"""

from __future__ import annotations

import pytest

from nyc_taxi_case.case_contract import (
    REQUIRED_TLC_COLUMNS,
    SchemaContractError,
    extract_file_year_month,
    validate_required_columns,
)


# --------------------------------------------------------------------------- #
# REQUIRED_TLC_COLUMNS
# --------------------------------------------------------------------------- #
class TestRequiredColumns:
    def test_exactly_the_five_case_columns(self) -> None:
        assert REQUIRED_TLC_COLUMNS == (
            "VendorID",
            "passenger_count",
            "total_amount",
            "tpep_pickup_datetime",
            "tpep_dropoff_datetime",
        )


# --------------------------------------------------------------------------- #
# validate_required_columns
# --------------------------------------------------------------------------- #
class TestValidateRequiredColumns:
    def test_accepts_exact_required_set(self) -> None:
        # Should not raise.
        validate_required_columns(list(REQUIRED_TLC_COLUMNS))

    def test_accepts_superset(self) -> None:
        # TLC parquet has 19 columns; we only require these 5 are present.
        extra = [*REQUIRED_TLC_COLUMNS, "PULocationID", "DOLocationID", "fare_amount"]
        validate_required_columns(extra)

    def test_rejects_missing_single_column(self) -> None:
        cols = [c for c in REQUIRED_TLC_COLUMNS if c != "total_amount"]
        with pytest.raises(SchemaContractError) as exc:
            validate_required_columns(cols)
        assert "total_amount" in str(exc.value)

    def test_rejects_multiple_missing_columns(self) -> None:
        cols = ["VendorID", "passenger_count"]
        with pytest.raises(SchemaContractError) as exc:
            validate_required_columns(cols)
        msg = str(exc.value)
        assert "total_amount" in msg
        assert "tpep_pickup_datetime" in msg
        assert "tpep_dropoff_datetime" in msg

    def test_rejects_empty_input(self) -> None:
        with pytest.raises(SchemaContractError):
            validate_required_columns([])


# --------------------------------------------------------------------------- #
# extract_file_year_month
# --------------------------------------------------------------------------- #
class TestExtractFileYearMonth:
    @pytest.mark.parametrize(
        ("path", "expected"),
        [
            ("yellow_tripdata_2023-01.parquet", "2023-01"),
            ("yellow_tripdata_2023-12.parquet", "2023-12"),
            (
                "/Volumes/workspace/nyc_taxi_landing/raw/"
                "year=2023/month=03/yellow_tripdata_2023-03.parquet",
                "2023-03",
            ),
            (
                "dbfs:/Volumes/workspace/x/y/yellow_tripdata_2022-11.parquet",
                "2022-11",
            ),
        ],
    )
    def test_extracts_from_various_paths(self, path: str, expected: str) -> None:
        assert extract_file_year_month(path) == expected

    @pytest.mark.parametrize(
        "path",
        [
            "",
            "yellow_tripdata.parquet",
            "yellow_tripdata_2023.parquet",
            "yellow_tripdata_2023-1.parquet",
            "yellow_tripdata_2023-13.parquet",
            "green_tripdata_2023-01.parquet",  # wrong category
            "/some/random/file.parquet",
        ],
    )
    def test_invalid_paths_return_none(self, path: str) -> None:
        assert extract_file_year_month(path) is None
