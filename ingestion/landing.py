# Databricks notebook source
"""Landing notebook — TLC parquet download into Volume UC + audit row.

This file is intended to run as a Databricks ``spark_python_task`` (or
notebook) and is the **only Spark/IO entry point of ticket #03**.

Responsibilities (CONTEXT.md "Landing", ADR-0002, ADR-0008):

1. Read the ingestion window from widgets (``start_year_month`` /
   ``end_year_month``) and the UC layout (``catalog``,
   ``monitoring_schema``, ``landing_volume_path``).
2. For every month in the inclusive window:

   * HEAD-probe the TLC URL (5s timeout, classification per
     :mod:`nyc_taxi_case.probe`).
   * If probe is ``OK``: stream-download the parquet into the Volume
     under ``year=YYYY/month=MM/yellow_tripdata_YYYY-MM.parquet``.
   * If probe fails: check whether the parquet is already on the
     Volume (idempotency / ``VOLUME_PREEXISTING`` fallback).
3. Aggregate the per-month outcomes into one
   :class:`~nyc_taxi_case.audit.LandingAuditRow` via
   :func:`nyc_taxi_case.audit.build_audit_row`, then write it to
   ``${catalog}.${monitoring_schema}.landing_audit`` (creating the
   table on first run with the ADR-0008 DDL).

Everything that can live outside Spark already does
(:mod:`nyc_taxi_case.window`, ``tlc_urls``, ``landing_paths``,
``probe``, ``audit``); the surface here is the thin Spark/IO shim
those modules are designed to be driven by.

Not in scope (later tickets):
* Bronze / Silver / DLT pipelines (#04, #05).
* The ``job_ingestion`` DAB that submits this notebook (#06).
* The post-DLT SQL task that fills ``pipeline_update_id`` (#06).
"""

# ruff: noqa: E402  # Databricks injects dbutils/spark before user imports

from __future__ import annotations

import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, cast

from nyc_taxi_case.audit import (
    LANDING_AUDIT_CREATE_TABLE_SQL,
    LandingAuditRow,
    MonthOutcome,
    ProbeResult,
    build_audit_row,
)
from nyc_taxi_case.landing_paths import build_volume_object_path, parse_volume_base
from nyc_taxi_case.probe import (
    PROBE_TIMEOUT_SECONDS,
    classify_probe_exception,
    classify_probe_response,
)
from nyc_taxi_case.tlc_urls import build_yellow_taxi_url
from nyc_taxi_case.window import expand_window

if TYPE_CHECKING:  # pragma: no cover - type-only imports
    from pyspark.sql import SparkSession
    from pyspark.sql.types import StructType

# --------------------------------------------------------------------------- #
# Databricks-injected globals
# --------------------------------------------------------------------------- #
# ``dbutils`` and ``spark`` are provided by the Databricks runtime. We
# tolerate their absence in plain pytest (this file is import-safe; the
# orchestration entry point only runs when invoked as ``__main__``).
# Using ``globals().get`` instead of a bare-name probe keeps Ruff B018
# quiet without resorting to per-line noqa.
dbutils = globals().get("dbutils")
spark = globals().get("spark")


# --------------------------------------------------------------------------- #
# Widget parsing
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class JobParams:
    """Parameters resolved from notebook widgets / task params."""

    start_year_month: str
    end_year_month: str
    catalog: str
    monitoring_schema: str
    landing_volume_path: str


_WIDGET_DEFAULTS: dict[str, str] = {
    # Defaults mirror resources/general_variables.yml so the notebook
    # is still runnable interactively without job parameters.
    "start_year_month": "2023-01",
    "end_year_month": "2023-05",
    "catalog": "workspace",
    "monitoring_schema": "nyc_taxi_monitoring",
    "landing_volume_path": "/Volumes/workspace/nyc_taxi_bronze/landing/yellow",
}


def _ensure_widgets() -> None:  # pragma: no cover - notebook-only path
    """Declare widgets idempotently. No-op outside a Databricks runtime."""
    if dbutils is None:
        return
    for name, default in _WIDGET_DEFAULTS.items():
        dbutils.widgets.text(name, default)  # type: ignore[union-attr]


def _read_params() -> JobParams:  # pragma: no cover - notebook-only path
    """Read params from widgets, falling back to the documented defaults."""
    if dbutils is None:
        raise RuntimeError("dbutils not available — run this as a Databricks task")
    get = dbutils.widgets.get  # type: ignore[union-attr]
    return JobParams(
        start_year_month=get("start_year_month"),
        end_year_month=get("end_year_month"),
        catalog=get("catalog"),
        monitoring_schema=get("monitoring_schema"),
        landing_volume_path=get("landing_volume_path"),
    )


# --------------------------------------------------------------------------- #
# Per-month IO
# --------------------------------------------------------------------------- #


def _file_size_or_zero(path: str) -> int:  # pragma: no cover - IO
    """Return the on-Volume size in bytes, or 0 if the file is absent."""
    import os  # local import keeps the module importable without OS quirks

    try:
        return os.path.getsize(path)
    except FileNotFoundError:
        return 0


def _head_probe(url: str) -> ProbeResult:  # pragma: no cover - IO
    """Fire a 5s HEAD against ``url`` and classify the outcome."""
    import requests  # imported lazily — requests not needed in pytest

    month_token = _month_from_url(url)
    try:
        resp = requests.head(url, allow_redirects=True, timeout=PROBE_TIMEOUT_SECONDS)
    except BaseException as exc:  # noqa: BLE001 — we classify, then keep going
        outcome = classify_probe_exception(exc)
        return ProbeResult(
            month=month_token,
            probe_status=outcome.probe_status,
            http_code=outcome.http_code,
        )
    classified = classify_probe_response(resp.status_code)
    return ProbeResult(
        month=month_token,
        probe_status=classified.probe_status,
        http_code=classified.http_code,
    )


def _month_from_url(url: str) -> str:
    """Extract ``YYYY-MM`` from a TLC URL. Trusts the canonical filename."""
    from nyc_taxi_case.schema import extract_file_year_month

    parsed = extract_file_year_month(url)
    if parsed is None:
        # _head_probe always builds URLs via build_yellow_taxi_url, so
        # reaching here means a programming error. Surface loudly.
        raise ValueError(f"could not extract YYYY-MM from URL {url!r}")
    return parsed


def _download_to_volume(url: str, dest_path: str) -> int:  # pragma: no cover - IO
    """Stream ``url`` to ``dest_path``. Returns bytes written.

    Streaming preserves byte fidelity vs the CloudFront origin
    (CONTEXT.md "Landing" — md5 preserved) and keeps memory bounded
    so a single notebook can ingest the whole 5-month window on a
    serverless task.
    """
    import os

    import requests

    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    bytes_written = 0
    with requests.get(url, stream=True, timeout=60) as resp:
        resp.raise_for_status()
        with open(dest_path, "wb") as fh:
            for chunk in resp.iter_content(chunk_size=1024 * 1024):
                if not chunk:
                    continue
                fh.write(chunk)
                bytes_written += len(chunk)
    return bytes_written


def _process_month(month: str, landing_volume_path: str) -> MonthOutcome:
    """Probe + download/skip/fail one month. Pure-ish orchestration.

    The IO bits (``_head_probe``, ``_download_to_volume``,
    ``_file_size_or_zero``) are module-level so a Databricks notebook
    runs them and a future integration test could monkeypatch them.
    """
    url = build_yellow_taxi_url(month)
    dest = build_volume_object_path(landing_volume_path, month)
    probe = _head_probe(url)

    if probe.probe_status == "OK":
        try:
            bytes_written = _download_to_volume(url, dest)
        except Exception as exc:  # pragma: no cover - defensive — IO failure
            # Demote a download failure (after a green probe) to FAILED
            # rather than crash the whole window. Audit will surface it.
            print(f"[landing] download failed for {month}: {exc}", file=sys.stderr)
            existing = _file_size_or_zero(dest)
            return MonthOutcome(
                month=month,
                status="SKIPPED_EXISTING" if existing > 0 else "FAILED",
                bytes_downloaded=0,
                bytes_in_volume=existing,
                probe=probe,
            )
        return MonthOutcome(
            month=month,
            status="DOWNLOADED",
            bytes_downloaded=bytes_written,
            bytes_in_volume=bytes_written,
            probe=probe,
        )

    # Probe failed. ADR-0002 fallback: if the parquet is already on the
    # Volume from a previous run / manual upload, treat as SKIPPED.
    existing = _file_size_or_zero(dest)
    if existing > 0:
        return MonthOutcome(
            month=month,
            status="SKIPPED_EXISTING",
            bytes_downloaded=0,
            bytes_in_volume=existing,
            probe=probe,
        )
    return MonthOutcome(
        month=month,
        status="FAILED",
        bytes_downloaded=0,
        bytes_in_volume=0,
        probe=probe,
    )


# --------------------------------------------------------------------------- #
# Audit writer
# --------------------------------------------------------------------------- #


def _audit_table_fqn(params: JobParams) -> str:
    return f"{params.catalog}.{params.monitoring_schema}.landing_audit"


def _ensure_audit_table(  # pragma: no cover - IO
    session: SparkSession, params: JobParams
) -> None:
    """Create the audit table on first run with the ADR-0008 schema."""
    session.sql(f"CREATE SCHEMA IF NOT EXISTS {params.catalog}.{params.monitoring_schema}")
    ddl = LANDING_AUDIT_CREATE_TABLE_SQL.format(table_fqn=_audit_table_fqn(params))
    session.sql(ddl)


def _ensure_landing_volume(  # pragma: no cover - IO
    session: SparkSession, params: JobParams
) -> None:
    """Create the Landing schema + Volume on first run.

    The Landing layer (CONTEXT.md) is a MANAGED Volume UC sitting under
    ``<catalog>.<bronze_schema>.<volume>``. ADR-0011 / ticket #06 wired
    every other UC object the pipeline needs (audit schema + table, DLT
    Bronze + Silver via the pipeline's ``catalog`` + ``target``), but
    the Landing schema/Volume themselves had to be created by hand —
    which silently broke ``_download_to_volume`` on a fresh workspace
    (``os.makedirs`` against a non-existent Volume returns
    ``FileNotFoundError`` AFTER a green probe, so the audit row reports
    the generic "outbound TLC bloqueado" message and downstream tasks
    skip via UPSTREAM_FAILED — see #06 Fix #4).

    Idempotent: ``IF NOT EXISTS`` on both statements. Cheap to run
    every launch.
    """
    base = parse_volume_base(params.landing_volume_path)
    session.sql(f"CREATE SCHEMA IF NOT EXISTS {base.catalog}.{base.schema}")
    session.sql(f"CREATE VOLUME IF NOT EXISTS {base.catalog}.{base.schema}.{base.volume}")


def _audit_row_to_spark_row(row: LandingAuditRow) -> dict[str, Any]:
    """Serialise an audit row into a dict ready for ``createDataFrame``."""
    return {
        "run_id": row.run_id,
        "job_run_id": row.job_run_id,
        "job_url": row.job_url,
        "pipeline_update_id": row.pipeline_update_id,
        "job_start_ts": row.job_start_ts,
        "job_end_ts": row.job_end_ts,
        "source_mode": row.source_mode,
        "probe_results": [
            {"month": p.month, "probe_status": p.probe_status, "http_code": p.http_code}
            for p in row.probe_results
        ],
        "start_year_month": row.start_year_month,
        "end_year_month": row.end_year_month,
        "months_requested": row.months_requested,
        "months_downloaded": row.months_downloaded,
        "months_skipped": row.months_skipped,
        "months_failed": row.months_failed,
        "bytes_downloaded": row.bytes_downloaded,
        "bytes_total_in_volume": row.bytes_total_in_volume,
        "status": row.status,
        "error_message": row.error_message,
    }


def _landing_audit_spark_schema() -> StructType:
    """Build the ``StructType`` mirroring ``LANDING_AUDIT_CREATE_TABLE_SQL``.

    Spark Connect (serverless runtime) refuses to infer the dataframe
    schema when a column is fully NULL — and ``pipeline_update_id`` is
    always ``None`` at landing time (the SQL backfill task fills it
    post-DLT, ADR-0008). ``error_message`` and ``probe_results[*].http_code``
    can also be ``None`` for some outcomes. Passing an explicit schema
    sidesteps the inference and matches the Delta table DDL one-to-one.

    Kept private and built lazily so the module stays importable in
    plain pytest (pyspark.sql.types is a pyspark-only dependency).
    """
    from pyspark.sql.types import (
        ArrayType,
        IntegerType,
        LongType,
        StringType,
        StructField,
        StructType,
        TimestampType,
    )

    probe_struct = StructType(
        [
            StructField("month", StringType(), nullable=False),
            StructField("probe_status", StringType(), nullable=False),
            # ADR-0002: TIMEOUT / CONN_ERR carry no HTTP code.
            StructField("http_code", IntegerType(), nullable=True),
        ]
    )

    # Order MUST match LANDING_AUDIT_COLUMNS (ADR-0008). Nullability
    # mirrors the DDL: pipeline_update_id and error_message are the
    # only top-level NULLable columns; the array columns are required
    # but their elements default to non-null.
    return StructType(
        [
            StructField("run_id", StringType(), nullable=False),
            StructField("job_run_id", StringType(), nullable=False),
            StructField("job_url", StringType(), nullable=False),
            StructField("pipeline_update_id", StringType(), nullable=True),
            StructField("job_start_ts", TimestampType(), nullable=False),
            StructField("job_end_ts", TimestampType(), nullable=False),
            StructField("source_mode", StringType(), nullable=False),
            StructField(
                "probe_results", ArrayType(probe_struct, containsNull=False), nullable=False
            ),
            StructField("start_year_month", StringType(), nullable=False),
            StructField("end_year_month", StringType(), nullable=False),
            StructField(
                "months_requested", ArrayType(StringType(), containsNull=False), nullable=False
            ),
            StructField(
                "months_downloaded", ArrayType(StringType(), containsNull=False), nullable=False
            ),
            StructField(
                "months_skipped", ArrayType(StringType(), containsNull=False), nullable=False
            ),
            StructField(
                "months_failed", ArrayType(StringType(), containsNull=False), nullable=False
            ),
            StructField("bytes_downloaded", LongType(), nullable=False),
            StructField("bytes_total_in_volume", LongType(), nullable=False),
            StructField("status", StringType(), nullable=False),
            StructField("error_message", StringType(), nullable=True),
        ]
    )


def _write_audit_row(  # pragma: no cover - IO
    session: SparkSession, params: JobParams, row: LandingAuditRow
) -> None:
    """Append a single row to ``landing_audit``.

    Uses an explicit schema (see :func:`_landing_audit_spark_schema`)
    because Spark Connect on the serverless runtime fails inference
    when any column in the single input row is ``None`` (notably
    ``pipeline_update_id`` and ``error_message`` on the SUCCESS path).
    """
    payload = _audit_row_to_spark_row(row)
    df = session.createDataFrame([payload], schema=_landing_audit_spark_schema())
    df.write.mode("append").saveAsTable(_audit_table_fqn(params))


# --------------------------------------------------------------------------- #
# Job-context helpers (job_run_id / job_url)
# --------------------------------------------------------------------------- #


def _resolve_job_context() -> tuple[str, str, str]:  # pragma: no cover - notebook-only
    """Return ``(run_id, job_run_id, job_url)`` from the Databricks task context.

    Falls back to placeholder strings when the context tags are
    missing (interactive notebook execution) so the row still inserts.
    """
    run_id = "interactive"
    job_run_id = "interactive"
    job_url = "interactive"
    if dbutils is None:
        return run_id, job_run_id, job_url
    try:
        ctx_json = dbutils.notebook.entry_point.getDbutils().notebook().getContext().toJson()  # type: ignore[union-attr]
        import json

        ctx = json.loads(ctx_json)
        tags = ctx.get("tags", {}) or {}
        run_id = tags.get("runId") or tags.get("taskRunId") or run_id
        job_run_id = tags.get("multitaskParentRunId") or tags.get("jobRunId") or job_run_id
        host = tags.get("browserHostName") or ""
        if host and job_run_id != "interactive":
            job_url = f"https://{host}/jobs/{tags.get('jobId', '')}/runs/{job_run_id}"
    except Exception as exc:  # noqa: BLE001 — context is best-effort
        print(f"[landing] could not resolve job context: {exc}", file=sys.stderr)
    return run_id, job_run_id, job_url


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #


def main() -> int:  # pragma: no cover - notebook-only orchestration
    """Run the landing flow end-to-end. Returns a process exit code."""
    _ensure_widgets()
    params = _read_params()
    months = expand_window(params.start_year_month, params.end_year_month)

    session = cast("SparkSession", spark)
    if session is None:
        raise RuntimeError("Spark session not available — run inside Databricks")
    _ensure_audit_table(session, params)
    _ensure_landing_volume(session, params)

    job_start = datetime.now(UTC)
    outcomes: list[MonthOutcome] = []
    for month in months:
        t0 = time.monotonic()
        outcome = _process_month(month, params.landing_volume_path)
        elapsed = time.monotonic() - t0
        print(
            f"[landing] {month} -> {outcome.status} "
            f"(probe={outcome.probe.probe_status}, "
            f"bytes_downloaded={outcome.bytes_downloaded}, "
            f"bytes_in_volume={outcome.bytes_in_volume}, "
            f"elapsed={elapsed:.2f}s)"
        )
        outcomes.append(outcome)
    job_end = datetime.now(UTC)

    run_id, job_run_id, job_url = _resolve_job_context()
    row = build_audit_row(
        run_id=run_id,
        job_run_id=job_run_id,
        job_url=job_url,
        job_start_ts=job_start,
        job_end_ts=job_end,
        start_year_month=params.start_year_month,
        end_year_month=params.end_year_month,
        outcomes=outcomes,
        # source_mode is HTTP whenever this notebook runs; the
        # VOLUME_PREEXISTING mode is reserved for the documented manual
        # fallback path where this notebook is NOT executed (operator
        # uploads files via `databricks fs cp` directly).
        source_mode="HTTP",
    )
    _write_audit_row(session, params, row)
    print(f"[landing] audit row written: status={row.status}")

    # Surface FAILED to the Databricks task UI so an operator sees red.
    # Notebook tasks treat ANY ``sys.exit`` (including ``sys.exit(0)``)
    # as a workload failure — they expect either natural cell completion
    # or ``dbutils.notebook.exit()``. So on the SUCCESS / PARTIAL path
    # we just return normally; on FAILED we raise so the task goes red
    # with the audit-row error message attached to the traceback.
    if row.status == "FAILED":
        raise RuntimeError(
            f"landing failed: {row.error_message or 'all months failed'}"
        )
    return 0


if __name__ == "__main__":  # pragma: no cover - notebook entrypoint
    main()
