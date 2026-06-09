"""Tests for nyc_taxi_case.landing_paths — Volume layout helpers.

Landing layer (CONTEXT.md) is the Volume UC where TLC parquets land
byte-a-byte under Hive-partitioned ``year=YYYY/month=MM/`` subdirs.
These helpers build the canonical object path the landing notebook
writes to, and parse one back to recover ``YYYY-MM`` for audit/debug.

Spark-free by design; the notebook only does the IO around them.
"""

from __future__ import annotations

import pytest

from nyc_taxi_case.landing_paths import (
    InvalidVolumeBaseError,
    VolumeBase,
    build_volume_object_path,
    parse_volume_base,
    parse_volume_object_path,
)
from nyc_taxi_case.window import InvalidYearMonthError


# --------------------------------------------------------------------------- #
# build_volume_object_path
# --------------------------------------------------------------------------- #
class TestBuildVolumeObjectPath:
    """Forward direction: ``(base, YYYY-MM)`` → full Hive-partitioned path."""

    def test_canonical_layout_for_jan_2023(self) -> None:
        base = "/Volumes/workspace/nyc_taxi_bronze/landing/yellow"
        assert build_volume_object_path(base, "2023-01") == (
            "/Volumes/workspace/nyc_taxi_bronze/landing/yellow/"
            "year=2023/month=01/yellow_tripdata_2023-01.parquet"
        )

    def test_dec_month_keeps_two_digit_zero_padding(self) -> None:
        # Defensive: month=12 must NOT become month=12 lacking a digit
        # (regression guard against accidental int() formatting).
        base = "/Volumes/workspace/nyc_taxi_bronze/landing/yellow"
        result = build_volume_object_path(base, "2023-12")
        assert "year=2023/month=12/" in result
        assert result.endswith("yellow_tripdata_2023-12.parquet")

    def test_trailing_slash_on_base_is_normalised(self) -> None:
        # General_variables.yml currently has no trailing slash, but
        # other callers (notebook, tests) might. We do not want
        # double-slashes in the resulting Volume path.
        with_slash = "/Volumes/workspace/nyc_taxi_bronze/landing/yellow/"
        without_slash = "/Volumes/workspace/nyc_taxi_bronze/landing/yellow"
        assert build_volume_object_path(with_slash, "2023-01") == build_volume_object_path(
            without_slash, "2023-01"
        )

    def test_invalid_year_month_propagates(self) -> None:
        # parse_year_month is the single source of validation rules;
        # this helper must not silently accept malformed input.
        base = "/Volumes/workspace/nyc_taxi_bronze/landing/yellow"
        with pytest.raises(InvalidYearMonthError):
            build_volume_object_path(base, "2023-1")

    @pytest.mark.parametrize("base", ["", "   ", "no-leading-slash/landing"])
    def test_invalid_base_raises(self, base: str) -> None:
        # Volume paths in UC must start with ``/Volumes/``. We refuse
        # empty / relative / clearly-wrong bases up front so the audit
        # row never reports an unusable path.
        with pytest.raises(InvalidVolumeBaseError):
            build_volume_object_path(base, "2023-01")


# --------------------------------------------------------------------------- #
# parse_volume_object_path
# --------------------------------------------------------------------------- #
class TestParseVolumeObjectPath:
    """Reverse direction: Hive-partitioned path → ``YYYY-MM`` or ``None``."""

    def test_canonical_path_returns_year_month(self) -> None:
        path = (
            "/Volumes/workspace/nyc_taxi_bronze/landing/yellow/"
            "year=2023/month=03/yellow_tripdata_2023-03.parquet"
        )
        assert parse_volume_object_path(path) == "2023-03"

    def test_path_without_partition_dirs_returns_none(self) -> None:
        # Filename alone is not enough — landing always writes under
        # year=/month= and the parser deliberately requires both, so
        # accidental writes outside the layout surface as ``None``.
        path = "/Volumes/workspace/nyc_taxi_bronze/landing/yellow/yellow_tripdata_2023-03.parquet"
        assert parse_volume_object_path(path) is None

    def test_path_with_wrong_filename_prefix_returns_none(self) -> None:
        # green_tripdata or fhv_tripdata must not match — yellow only.
        path = (
            "/Volumes/workspace/nyc_taxi_bronze/landing/yellow/"
            "year=2023/month=03/green_tripdata_2023-03.parquet"
        )
        assert parse_volume_object_path(path) is None

    def test_partition_inconsistent_with_filename_still_parses(self) -> None:
        # The parser trusts the filename (single source of YYYY-MM via
        # schema.FILE_YEAR_MONTH_PATTERN). Detecting partition vs
        # filename drift is a DLT/SQL concern, not this helper's.
        path = (
            "/Volumes/workspace/nyc_taxi_bronze/landing/yellow/"
            "year=2099/month=01/yellow_tripdata_2023-03.parquet"
        )
        assert parse_volume_object_path(path) == "2023-03"

    @pytest.mark.parametrize("path", ["", None])
    def test_empty_or_none_returns_none(self, path: object) -> None:
        assert parse_volume_object_path(path) is None  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# parse_volume_base
# --------------------------------------------------------------------------- #
class TestParseVolumeBase:
    """``(/Volumes/<cat>/<schema>/<vol>[/...])`` → ``VolumeBase``."""

    def test_canonical_landing_base_decomposes_to_three_parts(self) -> None:
        assert parse_volume_base("/Volumes/workspace/nyc_taxi_bronze/landing/yellow") == (
            VolumeBase(catalog="workspace", schema="nyc_taxi_bronze", volume="landing")
        )

    def test_trailing_slash_tolerated(self) -> None:
        assert parse_volume_base("/Volumes/workspace/nyc_taxi_bronze/landing/").volume == "landing"

    def test_bare_three_segment_path_is_enough(self) -> None:
        # /Volumes/<cat>/<schema>/<volume> with no subpath is the minimal
        # valid form — landing.py builds it for catalog-only DDL too.
        assert parse_volume_base("/Volumes/c/s/v") == VolumeBase(
            catalog="c", schema="s", volume="v"
        )

    @pytest.mark.parametrize("base", ["", "   "])
    def test_empty_or_blank_raises(self, base: str) -> None:
        with pytest.raises(InvalidVolumeBaseError, match="non-empty"):
            parse_volume_base(base)

    def test_non_uc_prefix_raises(self) -> None:
        with pytest.raises(InvalidVolumeBaseError, match="/Volumes/"):
            parse_volume_base("/dbfs/workspace/nyc_taxi_bronze/landing/yellow")

    @pytest.mark.parametrize(
        "base",
        [
            "/Volumes/workspace",
            "/Volumes/workspace/nyc_taxi_bronze",
            "/Volumes/workspace/nyc_taxi_bronze/",
        ],
    )
    def test_fewer_than_three_segments_raises(self, base: str) -> None:
        with pytest.raises(InvalidVolumeBaseError, match="catalog.*schema.*volume"):
            parse_volume_base(base)
