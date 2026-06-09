"""Schema contract and filename parsing for TLC Yellow Taxi data.

This module owns two things the case treats as load-bearing:

1. The **required 5 columns** the case statement demands the pipeline
   surface end-to-end. They are validated at CI time against the
   downloaded TLC schema (caught at PR time, not at midnight in
   production). See CONTEXT.md "Expectations" and ADR-0007.

2. The **file_year_month** regex that extracts the declared month from
   a TLC parquet filename. It is later compared with the row-level
   ``pickup_year_month`` in DLT expectation #6a (Silver) to flag rows
   whose pickup timestamp falls outside the file's declared month.
   See CONTEXT.md "file_year_month" and ADR-0004.

The module is Spark-free; the column validator takes a plain list of
strings so callers (CI test, Bronze warn expectation) can feed it from
either ``df.columns`` or a hand-written manifest.
"""

from __future__ import annotations

import re

__all__ = [
    "FILE_YEAR_MONTH_PATTERN",
    "REQUIRED_TLC_COLUMNS",
    "SchemaContractError",
    "extract_file_year_month",
    "validate_required_columns",
]

#: The five columns the case statement requires on Silver/Gold.
#: Order is significant only for human readability; validation is
#: set-based (missing detection only — supersets are allowed because
#: real TLC parquets carry 19 columns).
REQUIRED_TLC_COLUMNS: tuple[str, ...] = (
    "VendorID",
    "passenger_count",
    "total_amount",
    "tpep_pickup_datetime",
    "tpep_dropoff_datetime",
)

#: Matches ``yellow_tripdata_YYYY-MM.parquet`` anywhere in a filesystem
#: path. Anchored to the basename via the explicit ``yellow_tripdata_``
#: prefix so green/fhv/fhvhv filenames do not accidentally match.
FILE_YEAR_MONTH_PATTERN: re.Pattern[str] = re.compile(
    r"yellow_tripdata_(\d{4}-(?:0[1-9]|1[0-2]))\.parquet"
)


class SchemaContractError(ValueError):
    """Raised when a column list does not satisfy the case contract."""


def validate_required_columns(columns: list[str]) -> None:
    """Assert that every required TLC column is present in ``columns``.

    Supersets are allowed: real TLC parquets carry 19 columns, the case
    only requires 5. We only flag *missing* required columns.

    Raises:
        SchemaContractError: one or more required columns are absent.
            The message lists every missing column to avoid the
            whack-a-mole of fixing one at a time.
    """
    present = set(columns)
    missing = [c for c in REQUIRED_TLC_COLUMNS if c not in present]
    if missing:
        raise SchemaContractError(
            "missing required TLC columns: " + ", ".join(missing)
        )


def extract_file_year_month(path: str) -> str | None:
    """Return ``YYYY-MM`` extracted from a TLC yellow_tripdata filename.

    Works on bare filenames or full Volume/DBFS paths. Returns ``None``
    rather than raising so the caller (DLT expectation #6a, audit
    writer) can treat "no match" as a soft signal rather than a hard
    failure. Hard failures live in the DLT expectations layer.
    """
    if not path:
        return None
    match = FILE_YEAR_MONTH_PATTERN.search(path)
    if match is None:
        return None
    return match.group(1)
