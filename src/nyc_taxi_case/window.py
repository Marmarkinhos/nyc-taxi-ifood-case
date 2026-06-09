"""Ingestion window parsing and expansion.

A "Janela de ingestão" (CONTEXT.md) is the inclusive [start, end] range
of TLC months a single ``job_ingestion`` run must process. The two
boundary values arrive as job parameters ``--start_year_month`` and
``--end_year_month`` in the canonical ``YYYY-MM`` form.

This module is intentionally Spark-free so it can be exercised by
plain pytest in CI without a Databricks runtime.
"""

from __future__ import annotations

import re

__all__ = [
    "InvalidYearMonthError",
    "InvalidYearMonthRangeError",
    "YEAR_MONTH_PATTERN",
    "expand_window",
    "parse_year_month",
]

# Strict canonical form: 4-digit year, dash, zero-padded month 01-12.
# No leading/trailing whitespace tolerated — explicit beats implicit
# for a parameter that drives downstream filename construction.
YEAR_MONTH_PATTERN: re.Pattern[str] = re.compile(r"^(\d{4})-(0[1-9]|1[0-2])$")


class InvalidYearMonthError(ValueError):
    """Raised when a string does not match the canonical ``YYYY-MM`` form."""


class InvalidYearMonthRangeError(ValueError):
    """Raised when an ingestion window has end strictly before start."""


def parse_year_month(value: str) -> tuple[int, int]:
    """Parse a canonical ``YYYY-MM`` string into ``(year, month)``.

    Raises:
        InvalidYearMonthError: input does not match ``YEAR_MONTH_PATTERN``.
    """
    if not isinstance(value, str):  # defensive: callers pass argparse strings
        raise InvalidYearMonthError(f"expected str, got {type(value).__name__}")
    match = YEAR_MONTH_PATTERN.match(value)
    if match is None:
        raise InvalidYearMonthError(
            f"invalid year-month {value!r}; expected canonical 'YYYY-MM' (e.g. '2023-01')"
        )
    year = int(match.group(1))
    month = int(match.group(2))
    return year, month


def expand_window(start: str, end: str) -> list[str]:
    """Expand an inclusive ingestion window into the list of ``YYYY-MM`` months.

    ``expand_window("2023-01", "2023-05")`` yields the five strings
    ``["2023-01", "2023-02", "2023-03", "2023-04", "2023-05"]``.

    The window is **inclusive on both ends** to match how the case
    statement reads ("Jan–Maio 2023" = 5 months, not 4).

    Raises:
        InvalidYearMonthError: either boundary fails parsing.
        InvalidYearMonthRangeError: ``end`` is strictly before ``start``.
    """
    start_year, start_month = parse_year_month(start)
    end_year, end_month = parse_year_month(end)

    start_ordinal = start_year * 12 + (start_month - 1)
    end_ordinal = end_year * 12 + (end_month - 1)

    if end_ordinal < start_ordinal:
        raise InvalidYearMonthRangeError(
            f"end {end!r} is before start {start!r}; window must be ascending"
        )

    months: list[str] = []
    for ordinal in range(start_ordinal, end_ordinal + 1):
        year, month_zero_indexed = divmod(ordinal, 12)
        month = month_zero_indexed + 1
        months.append(f"{year:04d}-{month:02d}")
    return months
