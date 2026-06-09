"""Tests for the Spark-free seams of ingestion/landing.py.

We intentionally do NOT exercise the Spark / requests / dbutils
codepaths here — those live behind ``# pragma: no cover`` and are
validated only on Databricks (ticket #06 wires the DAB). What this
module pins is the per-month decision tree and the audit-row
serialisation, both of which run identically on any Python.

The notebook lives outside the installed package, so we add its
parent dir to ``sys.path`` and import it directly.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "ingestion"))

import landing  # type: ignore[import-not-found]  # noqa: E402

if TYPE_CHECKING:
    pass


from nyc_taxi_case.audit import LandingAuditRow, MonthOutcome, ProbeResult  # noqa: E402

LANDING_BASE = "/Volumes/workspace/nyc_taxi_bronze/landing/yellow"


# --------------------------------------------------------------------------- #
# _month_from_url — defensive parser around TLC URLs
# --------------------------------------------------------------------------- #
class TestMonthFromUrl:
    def test_canonical_url_yields_year_month(self) -> None:
        url = "https://d37ci6vzurychx.cloudfront.net/trip-data/yellow_tripdata_2023-03.parquet"
        assert landing._month_from_url(url) == "2023-03"

    def test_non_canonical_url_raises(self) -> None:
        # _process_month always builds URLs via build_yellow_taxi_url,
        # so an unparseable URL here is a programming bug — surface it.
        with pytest.raises(ValueError, match="extract YYYY-MM"):
            landing._month_from_url("https://example.com/random.parquet")


# --------------------------------------------------------------------------- #
# _process_month — decision tree (probe x download x volume-existence)
# --------------------------------------------------------------------------- #
class TestProcessMonth:
    """The four branches of the per-month state machine."""

    @pytest.fixture
    def patch_io(self, monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
        """Stub out the three IO seams so we can drive the truth table."""
        calls: dict[str, object] = {
            "probe_status": "OK",
            "probe_code": 200,
            "download_bytes": 0,
            "download_exc": None,
            "volume_bytes": 0,
            "head_calls": 0,
            "download_calls": 0,
        }

        def fake_head_probe(url: str) -> ProbeResult:
            calls["head_calls"] = int(calls["head_calls"]) + 1  # type: ignore[arg-type]
            month = landing._month_from_url(url)
            return ProbeResult(
                month=month,
                probe_status=str(calls["probe_status"]),
                http_code=calls["probe_code"],  # type: ignore[arg-type]
            )

        def fake_download(url: str, dest: str) -> int:  # noqa: ARG001
            calls["download_calls"] = int(calls["download_calls"]) + 1  # type: ignore[arg-type]
            if calls["download_exc"] is not None:
                raise calls["download_exc"]  # type: ignore[misc]
            return int(calls["download_bytes"])  # type: ignore[arg-type]

        def fake_file_size(path: str) -> int:  # noqa: ARG001
            return int(calls["volume_bytes"])  # type: ignore[arg-type]

        monkeypatch.setattr(landing, "_head_probe", fake_head_probe)
        monkeypatch.setattr(landing, "_download_to_volume", fake_download)
        monkeypatch.setattr(landing, "_file_size_or_zero", fake_file_size)
        return calls

    def test_probe_ok_downloads(self, patch_io: dict[str, object]) -> None:
        patch_io["probe_status"] = "OK"
        patch_io["download_bytes"] = 1024
        outcome = landing._process_month("2023-01", LANDING_BASE)

        assert outcome.status == "DOWNLOADED"
        assert outcome.bytes_downloaded == 1024
        assert outcome.bytes_in_volume == 1024  # what we just wrote
        assert outcome.probe.probe_status == "OK"
        assert patch_io["download_calls"] == 1

    def test_probe_fail_with_existing_file_is_skipped(self, patch_io: dict[str, object]) -> None:
        # ADR-0002 fallback path: probe blocked but operator pre-loaded
        # the parquet via `databricks fs cp`. We treat it as idempotent
        # skip rather than failure.
        patch_io["probe_status"] = "HTTP_ERR"
        patch_io["probe_code"] = 404
        patch_io["volume_bytes"] = 47_673_370  # real Jan 2023 size

        outcome = landing._process_month("2023-01", LANDING_BASE)

        assert outcome.status == "SKIPPED_EXISTING"
        assert outcome.bytes_downloaded == 0
        assert outcome.bytes_in_volume == 47_673_370
        assert outcome.probe.probe_status == "HTTP_ERR"
        assert patch_io["download_calls"] == 0  # no download attempted

    def test_probe_fail_with_no_file_is_failed(self, patch_io: dict[str, object]) -> None:
        patch_io["probe_status"] = "TIMEOUT"
        patch_io["probe_code"] = None
        patch_io["volume_bytes"] = 0

        outcome = landing._process_month("2023-01", LANDING_BASE)

        assert outcome.status == "FAILED"
        assert outcome.bytes_downloaded == 0
        assert outcome.bytes_in_volume == 0
        assert outcome.probe.probe_status == "TIMEOUT"
        assert patch_io["download_calls"] == 0

    def test_probe_ok_download_fails_falls_back_to_existing(
        self, patch_io: dict[str, object]
    ) -> None:
        # Probe said GREEN but the GET 5xx'd mid-stream. If the Volume
        # already has the file (idempotent rerun), keep going; otherwise
        # mark FAILED. This branch keeps a partial outage from poisoning
        # months that already landed previously.
        patch_io["probe_status"] = "OK"
        patch_io["download_exc"] = RuntimeError("simulated 503 mid-stream")
        patch_io["volume_bytes"] = 500

        outcome = landing._process_month("2023-01", LANDING_BASE)

        assert outcome.status == "SKIPPED_EXISTING"
        assert outcome.bytes_downloaded == 0
        assert outcome.bytes_in_volume == 500


# --------------------------------------------------------------------------- #
# _audit_row_to_spark_row — Spark-free serialisation
# --------------------------------------------------------------------------- #
class TestAuditRowToSparkRow:
    def _row(self) -> LandingAuditRow:
        return LandingAuditRow(
            run_id="r1",
            job_run_id="j1",
            job_url="https://example/jobs/1/runs/1",
            pipeline_update_id=None,
            job_start_ts=datetime(2026, 6, 9, 14, 0, tzinfo=UTC),
            job_end_ts=datetime(2026, 6, 9, 14, 5, tzinfo=UTC),
            source_mode="HTTP",
            probe_results=[
                ProbeResult(month="2023-01", probe_status="OK", http_code=200),
                ProbeResult(month="2023-02", probe_status="TIMEOUT", http_code=None),
            ],
            start_year_month="2023-01",
            end_year_month="2023-02",
            months_requested=["2023-01", "2023-02"],
            months_downloaded=["2023-01"],
            months_skipped=[],
            months_failed=["2023-02"],
            bytes_downloaded=100,
            bytes_total_in_volume=100,
            status="PARTIAL",
            error_message="failed months: 2023-02",
        )

    def test_top_level_keys_match_audit_columns(self) -> None:
        from nyc_taxi_case.audit import LANDING_AUDIT_COLUMNS

        payload = landing._audit_row_to_spark_row(self._row())
        # Sorted comparison: schema column order is enforced by the
        # CREATE TABLE DDL; dict order here is informational.
        assert sorted(payload.keys()) == sorted(LANDING_AUDIT_COLUMNS)

    def test_probe_results_serialise_as_list_of_dicts(self) -> None:
        payload = landing._audit_row_to_spark_row(self._row())
        probes = payload["probe_results"]
        assert isinstance(probes, list)
        assert probes[0] == {"month": "2023-01", "probe_status": "OK", "http_code": 200}
        assert probes[1] == {"month": "2023-02", "probe_status": "TIMEOUT", "http_code": None}

    def test_timestamps_kept_as_datetime_objects(self) -> None:
        # Spark createDataFrame is happy with Python datetimes; preserving
        # them (vs ISO strings) keeps TIMESTAMP semantics intact.
        payload = landing._audit_row_to_spark_row(self._row())
        assert isinstance(payload["job_start_ts"], datetime)
        assert isinstance(payload["job_end_ts"], datetime)

    def test_pipeline_update_id_is_null_on_landing_write(self) -> None:
        # ADR-0008: landing writes NULL; post-DLT SQL task fills it (#06).
        payload = landing._audit_row_to_spark_row(self._row())
        assert payload["pipeline_update_id"] is None


# --------------------------------------------------------------------------- #
# _resolve_job_context — widget-driven job-context resolution (ticket #15)
# --------------------------------------------------------------------------- #
class TestResolveJobContext:
    """Pins the Path B fix for #15: read job context from widgets, not tags.

    Each test rebuilds a minimal ``dbutils`` stub that only carries a
    ``widgets.get`` callable, monkeypatches it onto ``landing.dbutils``,
    then exercises ``_resolve_job_context``. This is the same surface
    a Databricks ``notebook_task`` exposes (after
    ``base_parameters`` are wired in ``resources/job_ingestion.yml``).
    """

    @staticmethod
    def _install_widgets(monkeypatch: pytest.MonkeyPatch, values: dict[str, str]) -> None:
        """Stub ``landing.dbutils`` with a widgets backend over ``values``.

        ``KeyError`` is raised for unknown widget names — matches the
        real Databricks behaviour and lets us exercise the
        widget-missing fallback branch.
        """

        class _Widgets:
            def get(self, name: str) -> str:
                if name not in values:
                    raise KeyError(name)
                return values[name]

        class _DBUtils:
            widgets = _Widgets()

        monkeypatch.setattr(landing, "dbutils", _DBUtils())

    def test_no_dbutils_returns_interactive_triple(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Plain pytest path (no Databricks runtime): the module-level
        # ``dbutils`` is ``None``. The function must short-circuit
        # without touching anything.
        monkeypatch.setattr(landing, "dbutils", None)
        assert landing._resolve_job_context() == (
            "interactive",
            "interactive",
            "interactive",
        )

    def test_widgets_with_job_run_id_returns_widget_values(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Happy path: ``base_parameters`` injected the dynamic values
        # so the widgets carry the real run ids. The trio must come
        # through verbatim — the downstream
        # ``update_landing_audit.sql`` filters on ``job_run_id``
        # equality, so any mangling here breaks the SQL UPDATE.
        self._install_widgets(
            monkeypatch,
            {
                "task_run_id": "987654321",
                "job_run_id": "1073098863810712",
                "job_url": (
                    "https://workspace.databricks.com/jobs/308012953236381/runs/1073098863810712"
                ),
            },
        )
        run_id, job_run_id, job_url = landing._resolve_job_context()
        assert run_id == "987654321"
        assert job_run_id == "1073098863810712"
        assert job_url == (
            "https://workspace.databricks.com/jobs/308012953236381/runs/1073098863810712"
        )

    def test_widgets_with_interactive_default_falls_back_to_triple(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Notebook launched standalone via the UI: widgets exist (they
        # are declared in ``_ensure_widgets``) but carry the literal
        # ``"interactive"`` default. The function must collapse the
        # whole trio back to ``"interactive"`` so the standalone-mode
        # contract from the acceptance criteria of #15 holds.
        self._install_widgets(
            monkeypatch,
            {
                "task_run_id": "interactive",
                "job_run_id": "interactive",
                "job_url": "interactive",
            },
        )
        assert landing._resolve_job_context() == (
            "interactive",
            "interactive",
            "interactive",
        )

    def test_widget_get_raises_falls_back_to_interactive(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Defensive branch: if the widget was somehow never declared
        # (e.g. someone runs the notebook against a stale runtime
        # before ``_ensure_widgets`` has run), ``dbutils.widgets.get``
        # raises. We must NOT crash the job — the audit row should
        # still insert with the standalone marker so the operator
        # spots the regression in ``landing_audit`` instead of in a
        # red task with a Py4J traceback.
        self._install_widgets(monkeypatch, {})  # any get(...) raises KeyError
        assert landing._resolve_job_context() == (
            "interactive",
            "interactive",
            "interactive",
        )


# --------------------------------------------------------------------------- #
# _audit_table_fqn — single source for the table name
# --------------------------------------------------------------------------- #
def test_audit_table_fqn_format() -> None:
    params = landing.JobParams(
        start_year_month="2023-01",
        end_year_month="2023-05",
        catalog="workspace",
        monitoring_schema="nyc_taxi_monitoring",
        landing_volume_path=LANDING_BASE,
    )
    assert landing._audit_table_fqn(params) == "workspace.nyc_taxi_monitoring.landing_audit"


# --------------------------------------------------------------------------- #
# Smoke: an empty MonthOutcome list never reaches the writer.
# This pins the contract between main() and build_audit_row.
# --------------------------------------------------------------------------- #
def test_month_outcome_validation_still_in_force() -> None:
    # Re-export sanity: importing the notebook should not have rebound
    # MonthOutcome to a looser type.
    with pytest.raises(ValueError):
        MonthOutcome(
            month="2023-01",
            status="GARBAGE",
            bytes_downloaded=0,
            bytes_in_volume=0,
            probe=ProbeResult(month="2023-01", probe_status="OK", http_code=200),
        )
