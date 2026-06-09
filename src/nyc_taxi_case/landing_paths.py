"""Volume UC layout helpers for the Landing layer.

The Landing layer (CONTEXT.md) lives in a Unity Catalog Volume at
``/Volumes/<catalog>/<bronze_schema>/landing/yellow`` and stores TLC
parquets under Hive-partitioned ``year=YYYY/month=MM/`` subdirectories.

This module owns the canonical path layout end-to-end:

* :func:`build_volume_object_path` constructs the full Volume object
  path the landing notebook writes to.
* :func:`parse_volume_object_path` recovers ``YYYY-MM`` from such a
  path for audit/debug logging.

Kept Spark-free so it can be exercised by pytest in CI without any
Databricks runtime, and so it has exactly one validation rule for
``YYYY-MM`` (delegated to :mod:`nyc_taxi_case.window`).
"""

from __future__ import annotations

import re

from nyc_taxi_case.schema import FILE_YEAR_MONTH_PATTERN
from nyc_taxi_case.window import parse_year_month

__all__ = [
    "InvalidVolumeBaseError",
    "build_volume_object_path",
    "parse_volume_object_path",
]


class InvalidVolumeBaseError(ValueError):
    """Raised when a Volume base path is empty, blank, or not absolute UC."""


# UC Volume paths are always absolute and start with ``/Volumes/`` —
# accepting anything else here would defer the failure to runtime IO
# with a much less helpful error.
_VOLUME_PREFIX = "/Volumes/"

# Recover YYYY-MM from a Hive-partitioned Landing path. We deliberately
# require BOTH the year= and month= directories: a parquet sitting at
# the top of the Volume violates the agreed layout and should surface
# as ``None`` rather than be silently accepted.
_PARTITIONED_PATH_PATTERN: re.Pattern[str] = re.compile(
    r"/year=\d{4}/month=(?:0[1-9]|1[0-2])/yellow_tripdata_\d{4}-(?:0[1-9]|1[0-2])\.parquet$"
)


def build_volume_object_path(base: str, year_month: str) -> str:
    """Return the canonical Volume object path for a Landing parquet.

    Args:
        base: Volume base path (e.g.
            ``/Volumes/workspace/nyc_taxi_bronze/landing/yellow``).
            A trailing slash is tolerated and stripped.
        year_month: Canonical ``YYYY-MM`` form. Validated via
            :func:`nyc_taxi_case.window.parse_year_month` to keep the
            rule in one place.

    Raises:
        InvalidVolumeBaseError: base is empty/blank or not a UC Volume path.
        nyc_taxi_case.window.InvalidYearMonthError: ``year_month``
            is not canonical ``YYYY-MM``.
    """
    if not base or not base.strip():
        raise InvalidVolumeBaseError("Volume base path must be a non-empty string")
    normalised = base.rstrip("/")
    if not normalised.startswith(_VOLUME_PREFIX):
        raise InvalidVolumeBaseError(
            f"Volume base path must start with {_VOLUME_PREFIX!r}, got {base!r}"
        )
    # parse_year_month enforces the canonical form and raises on garbage.
    year, month = parse_year_month(year_month)
    return f"{normalised}/year={year:04d}/month={month:02d}/yellow_tripdata_{year_month}.parquet"


def parse_volume_object_path(path: str | None) -> str | None:
    """Return ``YYYY-MM`` extracted from a Landing Volume path, or ``None``.

    The path must contain both ``year=YYYY/`` and ``month=MM/`` segments
    AND end with a canonical ``yellow_tripdata_YYYY-MM.parquet``
    filename. Anything else (top-of-volume parquets, green/fhv files,
    empty input) returns ``None`` so callers can treat it as a soft
    signal rather than a hard failure.

    When partition dirs and filename declare different months, the
    **filename** wins — drift detection is a DLT/SQL concern, not
    this helper's.
    """
    if not path:
        return None
    if _PARTITIONED_PATH_PATTERN.search(path) is None:
        return None
    # FILE_YEAR_MONTH_PATTERN is the single source of truth for the
    # YYYY-MM extraction; we already know the broader pattern matched.
    match = FILE_YEAR_MONTH_PATTERN.search(path)
    return match.group(1) if match is not None else None
