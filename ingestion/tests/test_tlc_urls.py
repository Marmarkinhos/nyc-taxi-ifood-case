"""Tests for nyc_taxi_case.tlc_urls — TLC CloudFront URL builder."""

from __future__ import annotations

import pytest

from nyc_taxi_case.tlc_urls import (
    TLC_CLOUDFRONT_BASE,
    InvalidYearMonthError,
    build_yellow_taxi_url,
)


class TestBuildYellowTaxiUrl:
    def test_returns_expected_url_for_case_month(self) -> None:
        assert build_yellow_taxi_url("2023-01") == (
            f"{TLC_CLOUDFRONT_BASE}/yellow_tripdata_2023-01.parquet"
        )

    @pytest.mark.parametrize(
        ("year_month", "expected_suffix"),
        [
            ("2023-05", "yellow_tripdata_2023-05.parquet"),
            ("2022-12", "yellow_tripdata_2022-12.parquet"),
            ("2024-09", "yellow_tripdata_2024-09.parquet"),
        ],
    )
    def test_returns_correct_filename_for_various_months(
        self, year_month: str, expected_suffix: str
    ) -> None:
        url = build_yellow_taxi_url(year_month)
        assert url.endswith(expected_suffix)
        assert url.startswith(TLC_CLOUDFRONT_BASE)

    def test_base_is_the_tlc_cloudfront_validated_in_probe(self) -> None:
        # ADR-0010 / CONTEXT.md: HTTP landing mode hits this exact host
        # (probe 2026-06-08 returned STATUS=200 in 0.10s).
        assert TLC_CLOUDFRONT_BASE == (
            "https://d37ci6vzurychx.cloudfront.net/trip-data"
        )

    @pytest.mark.parametrize(
        "bad",
        [
            "",
            "2023",
            "23-01",
            "2023-13",
            "2023-00",
            "2023/01",
        ],
    )
    def test_invalid_year_month_raises(self, bad: str) -> None:
        with pytest.raises(InvalidYearMonthError):
            build_yellow_taxi_url(bad)
