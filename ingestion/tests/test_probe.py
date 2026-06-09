"""Tests for nyc_taxi_case.probe — ADR-0002 HEAD classification truth table."""

from __future__ import annotations

import pytest

from nyc_taxi_case.probe import (
    PROBE_TIMEOUT_SECONDS,
    classify_probe_exception,
    classify_probe_response,
)


class TestClassifyProbeResponse:
    @pytest.mark.parametrize("code", [200, 204, 206, 299])
    def test_2xx_is_ok(self, code: int) -> None:
        outcome = classify_probe_response(code)
        assert outcome.probe_status == "OK"
        assert outcome.http_code == code

    @pytest.mark.parametrize("code", [301, 302, 404, 500, 503])
    def test_non_2xx_is_http_err_with_code(self, code: int) -> None:
        # We preserve the code so 404 (month missing) is distinguishable
        # from 503 (transient outage) in the audit row.
        outcome = classify_probe_response(code)
        assert outcome.probe_status == "HTTP_ERR"
        assert outcome.http_code == code


class TestClassifyProbeException:
    def test_timeout_subclass_yields_timeout(self) -> None:
        # We classify by class-name substring to avoid an import-time
        # dependency on ``requests``. ReadTimeout / ConnectTimeout
        # both contain "Timeout" — pin the rule.
        class ReadTimeout(Exception):
            pass

        outcome = classify_probe_exception(ReadTimeout())
        assert outcome.probe_status == "TIMEOUT"
        assert outcome.http_code is None

    def test_connection_error_yields_conn_err(self) -> None:
        class ConnectionError_(Exception):  # name mimics requests.ConnectionError
            pass

        outcome = classify_probe_exception(ConnectionError_())
        assert outcome.probe_status == "CONN_ERR"
        assert outcome.http_code is None

    def test_unknown_exception_yields_conn_err(self) -> None:
        # Conservative default: anything we cannot positively identify
        # as a timeout is bucketed as a connection error rather than
        # crashing the whole landing run.
        outcome = classify_probe_exception(RuntimeError("boom"))
        assert outcome.probe_status == "CONN_ERR"
        assert outcome.http_code is None


def test_probe_timeout_is_five_seconds() -> None:
    # Pin the ADR-0002 budget. Changing it requires updating the ADR.
    assert PROBE_TIMEOUT_SECONDS == 5.0
