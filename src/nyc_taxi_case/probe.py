"""HTTP HEAD probe classifier for the ADR-0002 landing flow.

The landing notebook fires a 5-second HEAD against the TLC CloudFront
URL before every download attempt. The probe outcome decides:

* whether to download via HTTP (probe ``OK``),
* or to fall back to ``VOLUME_PREEXISTING`` (probe failed but the
  parquet may already be on the Volume from a previous run).

This module owns the **classification rules** (status → probe_status,
exception type → probe_status). Kept Spark-free and IO-free so the
notebook can inject a real ``requests`` call while pytest exercises
the truth table with synthetic inputs.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = [
    "PROBE_TIMEOUT_SECONDS",
    "ProbeOutcome",
    "classify_probe_response",
    "classify_probe_exception",
]


# ADR-0002: 5 seconds is the agreed budget for a single HEAD probe.
# Long enough to absorb cold CloudFront edges, short enough that a
# fully-blocked outbound fails the whole 5-month window in <30s.
PROBE_TIMEOUT_SECONDS: float = 5.0


@dataclass(frozen=True, slots=True)
class ProbeOutcome:
    """Probe classification result.

    ``probe_status`` is one of the four values audited per ADR-0002 /
    ADR-0008: ``OK``, ``HTTP_ERR``, ``TIMEOUT``, ``CONN_ERR``.
    ``http_code`` is ``None`` when no response was received.
    """

    probe_status: str
    http_code: int | None


def classify_probe_response(status_code: int) -> ProbeOutcome:
    """Map a HEAD response's status code to a probe outcome.

    Anything in 2xx is ``OK``; everything else (3xx redirects we don't
    follow on HEAD, 4xx, 5xx) is ``HTTP_ERR`` with the code preserved
    so an operator can tell 404 (file genuinely missing for that month)
    from 503 (transient, retry-worthy).
    """
    if 200 <= status_code < 300:
        return ProbeOutcome(probe_status="OK", http_code=status_code)
    return ProbeOutcome(probe_status="HTTP_ERR", http_code=status_code)


def classify_probe_exception(exc: BaseException) -> ProbeOutcome:
    """Map a ``requests`` exception to a probe outcome.

    We use the exception class name (``Timeout``, ``ConnectionError``,
    ...) rather than ``isinstance`` so this module stays free of an
    import-time dependency on ``requests`` — keeping it usable in
    pytest without the dependency installed.
    """
    name = type(exc).__name__
    # Timeout subclasses include ConnectTimeout, ReadTimeout, etc.
    if "Timeout" in name:
        return ProbeOutcome(probe_status="TIMEOUT", http_code=None)
    return ProbeOutcome(probe_status="CONN_ERR", http_code=None)
