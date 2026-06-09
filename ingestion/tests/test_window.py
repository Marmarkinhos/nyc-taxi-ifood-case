"""Tests for nyc_taxi_case.window — ingestion window parsing/expansion.

Window terminology (CONTEXT.md):
- "Janela de ingestão" = which TLC files to process, declared via
  --start_year_month / --end_year_month (inclusive on both ends).
- NOT to be confused with row-level temporal validity
  (pickup_year_month vs file_year_month, enforced by DLT expectation #6a).
"""

from __future__ import annotations

import pytest

from nyc_taxi_case.window import (
    InvalidYearMonthError,
    InvalidYearMonthRangeError,
    expand_window,
    parse_year_month,
)


# --------------------------------------------------------------------------- #
# parse_year_month
# --------------------------------------------------------------------------- #
class TestParseYearMonth:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("2023-01", (2023, 1)),
            ("2023-12", (2023, 12)),
            ("1999-06", (1999, 6)),
            ("2087-03", (2087, 3)),  # TLC noise allows future years
        ],
    )
    def test_valid_formats(self, raw: str, expected: tuple[int, int]) -> None:
        assert parse_year_month(raw) == expected

    @pytest.mark.parametrize(
        "raw",
        [
            "",
            "2023",
            "2023-1",      # month must be zero-padded
            "23-01",       # year must be 4 digits
            "2023-13",     # month out of range
            "2023-00",     # month out of range
            "2023/01",     # wrong separator
            "2023-01-15",  # too many components
            "abc-de",
            " 2023-01 ",   # we do not silently strip
        ],
    )
    def test_invalid_formats_raise(self, raw: str) -> None:
        with pytest.raises(InvalidYearMonthError):
            parse_year_month(raw)


# --------------------------------------------------------------------------- #
# expand_window
# --------------------------------------------------------------------------- #
class TestExpandWindow:
    def test_case_window_jan_to_may_2023_yields_5_months(self) -> None:
        result = expand_window("2023-01", "2023-05")
        assert result == [
            "2023-01",
            "2023-02",
            "2023-03",
            "2023-04",
            "2023-05",
        ]

    def test_single_month_window_yields_one_item(self) -> None:
        assert expand_window("2023-03", "2023-03") == ["2023-03"]

    def test_window_crossing_year_boundary(self) -> None:
        assert expand_window("2022-11", "2023-02") == [
            "2022-11",
            "2022-12",
            "2023-01",
            "2023-02",
        ]

    def test_window_spans_multiple_years(self) -> None:
        result = expand_window("2022-12", "2024-01")
        assert len(result) == 14
        assert result[0] == "2022-12"
        assert result[-1] == "2024-01"

    def test_start_after_end_raises(self) -> None:
        with pytest.raises(InvalidYearMonthRangeError):
            expand_window("2023-05", "2023-01")

    def test_invalid_start_raises_parse_error(self) -> None:
        with pytest.raises(InvalidYearMonthError):
            expand_window("nope", "2023-05")

    def test_invalid_end_raises_parse_error(self) -> None:
        with pytest.raises(InvalidYearMonthError):
            expand_window("2023-01", "nope")
