"""Landing audit row construction (schema per ADR-0008).

The Landing notebook produces exactly one row in
``${prefix}monitoring.landing_audit`` per run. This module owns:

* The **17-column schema** (load-bearing — Gold filters by the last
  audit row's window via dbt ``sources.yml``).
* The **CREATE TABLE IF NOT EXISTS** DDL the notebook runs once.
* The **aggregation rules** that collapse per-month outcomes
  (probe + download result) into a single audit row, including the
  status decision tree (SUCCESS / PARTIAL / FAILED).

All public types here are Spark-free dataclasses; the notebook only
serialises them to a Spark Row when writing. Tests in
``ingestion/tests/test_audit.py`` pin both the schema and the
decision tree against ADR-0008.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from nyc_taxi_case.window import expand_window

__all__ = [
    "LANDING_AUDIT_COLUMNS",
    "LANDING_AUDIT_CREATE_TABLE_SQL",
    "LandingAuditRow",
    "MonthOutcome",
    "ProbeResult",
    "build_audit_row",
]

# --------------------------------------------------------------------------- #
# Schema contract (ADR-0008)
# --------------------------------------------------------------------------- #

#: Column names and order for ``landing_audit``. Mirrors ADR-0008
#: verbatim — see test_audit.TestSchemaContract.
LANDING_AUDIT_COLUMNS: tuple[str, ...] = (
    "run_id",
    "job_run_id",
    "job_url",
    "pipeline_update_id",
    "job_start_ts",
    "job_end_ts",
    "source_mode",
    "probe_results",
    "start_year_month",
    "end_year_month",
    "months_requested",
    "months_downloaded",
    "months_skipped",
    "months_failed",
    "bytes_downloaded",
    "bytes_total_in_volume",
    "status",
    "error_message",
)

#: ``CREATE TABLE IF NOT EXISTS`` DDL for ``landing_audit``. ``{table_fqn}``
#: is a format placeholder filled by the notebook with
#: ``<catalog>.<monitoring_schema>.landing_audit``. Delta is the only
#: format Free Edition serves out of UC; explicit USING avoids surprises.
LANDING_AUDIT_CREATE_TABLE_SQL: str = """\
CREATE TABLE IF NOT EXISTS {table_fqn} (
  run_id                STRING,
  job_run_id            STRING,
  job_url               STRING,
  pipeline_update_id    STRING,
  job_start_ts          TIMESTAMP,
  job_end_ts            TIMESTAMP,
  source_mode           STRING,
  probe_results         ARRAY<STRUCT<
                          month: STRING,
                          probe_status: STRING,
                          http_code: INT
                        >>,
  start_year_month      STRING,
  end_year_month        STRING,
  months_requested      ARRAY<STRING>,
  months_downloaded     ARRAY<STRING>,
  months_skipped        ARRAY<STRING>,
  months_failed         ARRAY<STRING>,
  bytes_downloaded      BIGINT,
  bytes_total_in_volume BIGINT,
  status                STRING,
  error_message         STRING
)
USING DELTA
"""


# --------------------------------------------------------------------------- #
# Allowed-value tables
# --------------------------------------------------------------------------- #

# ProbeResult.probe_status: ADR-0002 (probe HEAD result classes).
_ALLOWED_PROBE_STATUSES: frozenset[str] = frozenset({"OK", "TIMEOUT", "HTTP_ERR", "CONN_ERR"})

# MonthOutcome.status: lifecycle of one month within the window.
#   DOWNLOADED       -> probe OK + HTTP body written this run
#   SKIPPED_EXISTING -> file already on the Volume (idempotency)
#   FAILED           -> probe failed and no usable Volume file
_ALLOWED_MONTH_STATUSES: frozenset[str] = frozenset({"DOWNLOADED", "SKIPPED_EXISTING", "FAILED"})

# LandingAuditRow.source_mode: ADR-0008 §Decision.
_ALLOWED_SOURCE_MODES: frozenset[str] = frozenset({"HTTP", "VOLUME_PREEXISTING"})


# --------------------------------------------------------------------------- #
# Building blocks
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class ProbeResult:
    """Outcome of one ADR-0002 HEAD probe against the TLC CloudFront.

    ``http_code`` is ``None`` for ``TIMEOUT`` and ``CONN_ERR`` (no
    response was received). For ``OK`` and ``HTTP_ERR`` it carries the
    status code so an operator can distinguish 404 (file genuinely
    missing for that month) from 5xx (transient).
    """

    month: str
    probe_status: str
    http_code: int | None

    def __post_init__(self) -> None:
        if self.probe_status not in _ALLOWED_PROBE_STATUSES:
            raise ValueError(
                f"invalid probe_status {self.probe_status!r}; "
                f"expected one of {sorted(_ALLOWED_PROBE_STATUSES)}"
            )


@dataclass(frozen=True, slots=True)
class MonthOutcome:
    """End-to-end outcome of one month: probe + download/skip/fail.

    ``bytes_downloaded`` counts only what this run wrote (0 for SKIPPED
    and FAILED). ``bytes_in_volume`` counts what is currently sitting
    on the Volume for this month (0 if nothing landed). The split
    drives the ``bytes_downloaded`` vs ``bytes_total_in_volume`` columns
    in the audit row — ADR-0008 calls out that mixing them was a
    reconstructibility bug in the original 13-column schema.
    """

    month: str
    status: str
    bytes_downloaded: int
    bytes_in_volume: int
    probe: ProbeResult

    def __post_init__(self) -> None:
        if self.status not in _ALLOWED_MONTH_STATUSES:
            raise ValueError(
                f"invalid status {self.status!r}; expected one of {sorted(_ALLOWED_MONTH_STATUSES)}"
            )


# --------------------------------------------------------------------------- #
# Audit row
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class LandingAuditRow:
    """One row of ``landing_audit``. Field order matches ADR-0008."""

    run_id: str
    job_run_id: str
    job_url: str
    pipeline_update_id: str | None  # filled by SQL task post-DLT (#06)
    job_start_ts: datetime
    job_end_ts: datetime
    source_mode: str
    probe_results: list[ProbeResult]
    start_year_month: str
    end_year_month: str
    months_requested: list[str]
    months_downloaded: list[str]
    months_skipped: list[str]
    months_failed: list[str]
    bytes_downloaded: int
    bytes_total_in_volume: int
    status: str
    error_message: str | None = field(default=None)


# --------------------------------------------------------------------------- #
# Aggregator
# --------------------------------------------------------------------------- #


def build_audit_row(
    *,
    run_id: str,
    job_run_id: str,
    job_url: str,
    job_start_ts: datetime,
    job_end_ts: datetime,
    start_year_month: str,
    end_year_month: str,
    outcomes: list[MonthOutcome],
    source_mode: str,
    pipeline_update_id: str | None = None,
) -> LandingAuditRow:
    """Collapse per-month outcomes into one ``LandingAuditRow``.

    Status decision tree:

    * Every outcome ``DOWNLOADED`` or ``SKIPPED_EXISTING`` → ``SUCCESS``.
    * At least one ``FAILED`` AND at least one non-failure → ``PARTIAL``.
    * Every outcome ``FAILED`` → ``FAILED``.

    ``months_requested`` is reconstructed via
    :func:`nyc_taxi_case.window.expand_window` so it stays
    chronological even if ``outcomes`` arrives shuffled.

    Raises:
        ValueError: ``outcomes`` empty, or ``source_mode`` outside the
            ADR-0008 allowed set. Per-element validation happens in the
            ``MonthOutcome`` / ``ProbeResult`` constructors.
    """
    if not outcomes:
        raise ValueError("build_audit_row requires at least one MonthOutcome")
    if source_mode not in _ALLOWED_SOURCE_MODES:
        raise ValueError(
            f"invalid source_mode {source_mode!r}; expected one of {sorted(_ALLOWED_SOURCE_MODES)}"
        )

    months_requested = expand_window(start_year_month, end_year_month)

    # Iterate outcomes in chronological order so the per-status month
    # arrays are stable regardless of how the caller batched downloads.
    by_month = {o.month: o for o in outcomes}
    ordered = [by_month[m] for m in months_requested if m in by_month]

    months_downloaded = [o.month for o in ordered if o.status == "DOWNLOADED"]
    months_skipped = [o.month for o in ordered if o.status == "SKIPPED_EXISTING"]
    months_failed = [o.month for o in ordered if o.status == "FAILED"]
    bytes_downloaded = sum(o.bytes_downloaded for o in ordered)
    bytes_total_in_volume = sum(o.bytes_in_volume for o in ordered)
    probe_results = [o.probe for o in ordered]

    status, error_message = _status_and_error(
        months_failed=months_failed,
        non_failed_count=len(months_downloaded) + len(months_skipped),
    )

    return LandingAuditRow(
        run_id=run_id,
        job_run_id=job_run_id,
        job_url=job_url,
        pipeline_update_id=pipeline_update_id,
        job_start_ts=job_start_ts,
        job_end_ts=job_end_ts,
        source_mode=source_mode,
        probe_results=probe_results,
        start_year_month=start_year_month,
        end_year_month=end_year_month,
        months_requested=months_requested,
        months_downloaded=months_downloaded,
        months_skipped=months_skipped,
        months_failed=months_failed,
        bytes_downloaded=bytes_downloaded,
        bytes_total_in_volume=bytes_total_in_volume,
        status=status,
        error_message=error_message,
    )


def _status_and_error(*, months_failed: list[str], non_failed_count: int) -> tuple[str, str | None]:
    """Return ``(status, error_message)`` from the failed-months tally."""
    if not months_failed:
        return "SUCCESS", None
    if non_failed_count == 0:
        # Total failure: every month's probe failed. ADR-0002 mandates
        # we point operators at the VOLUME_PREEXISTING fallback runbook.
        return (
            "FAILED",
            (
                "all months failed probe/download: "
                f"{', '.join(months_failed)}. "
                "outbound TLC bloqueado — vide README seção VOLUME_PREEXISTING"
            ),
        )
    # PARTIAL: some months landed, others didn't. Surface which.
    return (
        "PARTIAL",
        f"failed months: {', '.join(months_failed)}",
    )
