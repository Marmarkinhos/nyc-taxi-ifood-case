"""Tests for nyc_taxi_case.audit — landing_audit row construction.

Schema is load-bearing (ADR-0008): downstream Gold reads
``landing_audit`` via dbt ``sources.yml`` to recover the ingestion
window of the last successful run. Any change here is a breaking
change. These tests pin the column set, the status decision tree,
and the aggregation rules from per-month outcomes to one audit row.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from nyc_taxi_case.audit import (
    LANDING_AUDIT_COLUMNS,
    LANDING_AUDIT_CREATE_TABLE_SQL,
    MonthOutcome,
    ProbeResult,
    build_audit_row,
)

# Stable timestamps so equality assertions stay deterministic.
JOB_START = datetime(2026, 6, 9, 14, 0, 0, tzinfo=UTC)
JOB_END = datetime(2026, 6, 9, 14, 5, 0, tzinfo=UTC)


# --------------------------------------------------------------------------- #
# Schema contract (ADR-0008)
# --------------------------------------------------------------------------- #
class TestSchemaContract:
    """ADR-0008 names and orders 17 columns. Both are load-bearing."""

    def test_column_set_matches_adr_0008(self) -> None:
        # If you change this set, you are making a breaking change to
        # downstream consumers (dbt sources, Gold filter, monitoring
        # view). Update ADR-0008 first.
        assert LANDING_AUDIT_COLUMNS == (
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

    def test_create_table_sql_mentions_every_column(self) -> None:
        sql = LANDING_AUDIT_CREATE_TABLE_SQL
        # Cheap structural assertion: every column name appears as an
        # identifier in the DDL. Catches typos when adding columns.
        for col in LANDING_AUDIT_COLUMNS:
            assert col in sql, f"column {col!r} missing from CREATE TABLE DDL"
        assert "CREATE TABLE IF NOT EXISTS" in sql
        # Schema FQN is a format placeholder so the notebook can fill
        # it from job parameters without us hardcoding ``workspace``.
        assert "{table_fqn}" in sql


# --------------------------------------------------------------------------- #
# build_audit_row — happy paths
# --------------------------------------------------------------------------- #
def _outcome(
    month: str,
    *,
    status: str = "DOWNLOADED",
    bytes_downloaded: int = 0,
    bytes_in_volume: int = 0,
    probe_status: str = "OK",
    http_code: int | None = 200,
) -> MonthOutcome:
    return MonthOutcome(
        month=month,
        status=status,
        bytes_downloaded=bytes_downloaded,
        bytes_in_volume=bytes_in_volume,
        probe=ProbeResult(month=month, probe_status=probe_status, http_code=http_code),
    )


class TestBuildAuditRow:
    def test_all_months_downloaded_yields_success(self) -> None:
        outcomes = [
            _outcome("2023-01", bytes_downloaded=100, bytes_in_volume=100),
            _outcome("2023-02", bytes_downloaded=200, bytes_in_volume=200),
        ]
        row = build_audit_row(
            run_id="r1",
            job_run_id="j1",
            job_url="https://example/job/1",
            job_start_ts=JOB_START,
            job_end_ts=JOB_END,
            start_year_month="2023-01",
            end_year_month="2023-02",
            outcomes=outcomes,
            source_mode="HTTP",
        )
        assert row.status == "SUCCESS"
        assert row.months_downloaded == ["2023-01", "2023-02"]
        assert row.months_skipped == []
        assert row.months_failed == []
        assert row.bytes_downloaded == 300
        assert row.bytes_total_in_volume == 300
        assert row.error_message is None
        assert row.pipeline_update_id is None  # filled by post-DLT SQL task

    def test_mixed_download_and_skip_is_still_success(self) -> None:
        # SUCCESS = "no month failed". Skipped months are idempotency,
        # not failure.
        outcomes = [
            _outcome("2023-01", status="DOWNLOADED", bytes_downloaded=100, bytes_in_volume=100),
            _outcome(
                "2023-02",
                status="SKIPPED_EXISTING",
                bytes_downloaded=0,
                bytes_in_volume=150,
            ),
        ]
        row = build_audit_row(
            run_id="r1",
            job_run_id="j1",
            job_url="https://example/job/1",
            job_start_ts=JOB_START,
            job_end_ts=JOB_END,
            start_year_month="2023-01",
            end_year_month="2023-02",
            outcomes=outcomes,
            source_mode="HTTP",
        )
        assert row.status == "SUCCESS"
        assert row.months_downloaded == ["2023-01"]
        assert row.months_skipped == ["2023-02"]
        assert row.months_failed == []
        assert row.bytes_downloaded == 100
        # bytes_total_in_volume sums what's actually on the Volume now,
        # NOT just what this run wrote. ADR-0008 calls this out.
        assert row.bytes_total_in_volume == 250

    def test_one_failed_month_yields_partial(self) -> None:
        outcomes = [
            _outcome("2023-01", status="DOWNLOADED", bytes_downloaded=100, bytes_in_volume=100),
            _outcome(
                "2023-02",
                status="FAILED",
                probe_status="HTTP_ERR",
                http_code=503,
            ),
        ]
        row = build_audit_row(
            run_id="r1",
            job_run_id="j1",
            job_url="https://example/job/1",
            job_start_ts=JOB_START,
            job_end_ts=JOB_END,
            start_year_month="2023-01",
            end_year_month="2023-02",
            outcomes=outcomes,
            source_mode="HTTP",
        )
        assert row.status == "PARTIAL"
        assert row.months_failed == ["2023-02"]
        assert row.error_message is not None and "2023-02" in row.error_message

    def test_all_failed_yields_failed(self) -> None:
        outcomes = [
            _outcome("2023-01", status="FAILED", probe_status="TIMEOUT", http_code=None),
            _outcome("2023-02", status="FAILED", probe_status="TIMEOUT", http_code=None),
        ]
        row = build_audit_row(
            run_id="r1",
            job_run_id="j1",
            job_url="https://example/job/1",
            job_start_ts=JOB_START,
            job_end_ts=JOB_END,
            start_year_month="2023-01",
            end_year_month="2023-02",
            outcomes=outcomes,
            source_mode="HTTP",
        )
        assert row.status == "FAILED"
        assert row.months_failed == ["2023-01", "2023-02"]
        assert row.error_message is not None
        # ADR-0002 mandates the README pointer when nothing landed.
        assert "VOLUME_PREEXISTING" in row.error_message

    def test_probe_results_preserved_in_input_order(self) -> None:
        # Order matters for human debugging: read top-to-bottom and
        # the months line up with the requested window.
        outcomes = [
            _outcome("2023-01"),
            _outcome("2023-02", probe_status="TIMEOUT", http_code=None),
            _outcome("2023-03"),
        ]
        row = build_audit_row(
            run_id="r1",
            job_run_id="j1",
            job_url="https://example/job/1",
            job_start_ts=JOB_START,
            job_end_ts=JOB_END,
            start_year_month="2023-01",
            end_year_month="2023-03",
            outcomes=outcomes,
            source_mode="HTTP",
        )
        assert [p.month for p in row.probe_results] == ["2023-01", "2023-02", "2023-03"]
        assert row.probe_results[1].probe_status == "TIMEOUT"
        assert row.probe_results[1].http_code is None


# --------------------------------------------------------------------------- #
# build_audit_row — validation
# --------------------------------------------------------------------------- #
class TestBuildAuditRowValidation:
    def test_empty_outcomes_rejected(self) -> None:
        # An empty window is a programming error upstream — not an
        # operational state to silently log.
        with pytest.raises(ValueError, match="at least one"):
            build_audit_row(
                run_id="r1",
                job_run_id="j1",
                job_url="https://example/job/1",
                job_start_ts=JOB_START,
                job_end_ts=JOB_END,
                start_year_month="2023-01",
                end_year_month="2023-01",
                outcomes=[],
                source_mode="HTTP",
            )

    def test_invalid_status_rejected(self) -> None:
        with pytest.raises(ValueError, match="status"):
            MonthOutcome(
                month="2023-01",
                status="BANANA",  # not in the allowed set
                bytes_downloaded=0,
                bytes_in_volume=0,
                probe=ProbeResult(month="2023-01", probe_status="OK", http_code=200),
            )

    def test_invalid_source_mode_rejected(self) -> None:
        outcomes = [_outcome("2023-01")]
        with pytest.raises(ValueError, match="source_mode"):
            build_audit_row(
                run_id="r1",
                job_run_id="j1",
                job_url="https://example/job/1",
                job_start_ts=JOB_START,
                job_end_ts=JOB_END,
                start_year_month="2023-01",
                end_year_month="2023-01",
                outcomes=outcomes,
                source_mode="FTP",  # not HTTP or VOLUME_PREEXISTING
            )

    def test_invalid_probe_status_rejected(self) -> None:
        with pytest.raises(ValueError, match="probe_status"):
            ProbeResult(month="2023-01", probe_status="WAT", http_code=200)


# --------------------------------------------------------------------------- #
# months_requested preserves window order regardless of outcome order
# --------------------------------------------------------------------------- #
class TestMonthsRequested:
    def test_months_requested_uses_expand_window_order(self) -> None:
        # If the caller shuffles outcomes (concurrent downloads etc),
        # months_requested still reads in chronological order.
        outcomes = [
            _outcome("2023-03"),
            _outcome("2023-01"),
            _outcome("2023-02"),
        ]
        row = build_audit_row(
            run_id="r1",
            job_run_id="j1",
            job_url="https://example/job/1",
            job_start_ts=JOB_START,
            job_end_ts=JOB_END,
            start_year_month="2023-01",
            end_year_month="2023-03",
            outcomes=outcomes,
            source_mode="HTTP",
        )
        assert row.months_requested == ["2023-01", "2023-02", "2023-03"]
